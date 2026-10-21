"""Gemma 4 E2B calls for the brain: llama-server at 127.0.0.1:8080, thinking off, greedy, one cached prefix per call type.
The payloads are the ones verified in spikes/scripts/voice_grab.py and grab_loop.py. Every call is returned as a record
(question, answer, milliseconds, provenance tag, server timings) so the brain can log it and show it on the brain view."""
import base64, os, re, sys, time
import cv2
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "bench"))
from client import timed_chat

TAG = "Gemma decision"
COLORS = ["red", "green", "blue", "white", "purple", "black", "silver", "yellow", "orange", "pink", "grey", "gray"]
SYN = {"white": {"white", "silver", "grey", "gray"}, "silver": {"silver", "white", "grey", "gray"}, "grey": {"grey", "gray", "silver", "white"},
       "gray": {"grey", "gray", "silver", "white"}, "purple": {"purple", "violet", "magenta"}, "red": {"red"}, "green": {"green"},
       "blue": {"blue"}, "black": {"black"}, "yellow": {"yellow", "gold"}, "orange": {"orange"}, "pink": {"pink"}}
BASE = {"model": "gemma4-e2b", "cache_prompt": True, "temperature": 0.0, "top_k": 1, "chat_template_kwargs": {"enable_thinking": False}}
HEAR_SYSTEM = ("You are a drinks host robot. The guest names the colour of the can they want. The guest may speak any language. "
               "Answer with the English colour word only, or none if no colour was named.")
HEAR_Q = "Which colour did the guest ask for?"
TAKE_Q = "Transcribe this audio in English."
# words that mean "let go" in a transcript; the yes/no judgement was 9/14 on synthetic clips, transcribe + keywords 14/14 (Mac, 2026-10-19)
TAKE_WORDS = ("take", "took", "got it", "have it", "let go", "thank", "give", "mine", "gracias", "dame", "lo tengo", "suelta", "merci",
              "donne", "danke", "gib", "谢谢", "給我", "给我", "拿", "放手")
VISION_SYSTEM = "You are a robot's vision module. Image left/right are robot left/right."
CROP_Q = "What is the main colour of this can? Answer with one colour word."
IN_HAND_Q = "Is the robot holding the soda can in its hand, off the table?"
HUMAN_HAND_Q = "Is a human hand touching the soda can that the robot is holding? The robot's own white hand does not count."
DESCRIBE_SYSTEM = "You label drink cans. Reply with at most four words: the colour, then the brand or flavour if readable, and any fruit pictured. No sentences."
DESCRIBE_Q = "Describe this drink can in at most four words: colour, brand or flavour, and any fruit pictured."   # V2_STRATEGY section 4; Mac, office crops: "Purple Sprite" / "Silver, Chi" in 225-240 ms, a flat crop "Grey, no brand"
CHOOSE_SYSTEM = ("You are a drinks host robot. The cans on the table are numbered: {cans}. The guest says which can they want, in any "
                 "language; they may name its colour, brand, flavour, picture, size or position. Answer with the number of that can only, "
                 "or none if no listed can matches.")
CHOOSE_Q = "Which can does the guest want?"


def jpeg_b64(img, size=(480, 336), quality=85):
    if size: img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode()


def image_part(img, size=(480, 336)):
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + jpeg_b64(img, size)}}


def audio_part(wav_bytes):
    return {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav_bytes).decode(), "format": "wav"}}


def colour_in(text):
    """First known colour word in a Gemma answer, or None."""
    return next((w for w in re.findall(r"[a-z]+", (text or "").lower()) if w in COLORS), None)


class Gemma:
    def __init__(self, base_url="http://127.0.0.1:8080/v1", on_record=None, chat=timed_chat):
        self.base_url, self.on_record, self.chat, self.n, self.timeout = base_url, on_record or (lambda r: None), chat, 0, 20.0

    def ask(self, kind, question, messages, max_tokens, stage=None, media=None, extra=None, tag=TAG):
        payload = dict(BASE, max_tokens=max_tokens, messages=messages); payload.update(extra or {})
        t0 = time.perf_counter(); err = None
        try: r = self.chat(self.base_url, payload, timeout=self.timeout)       # bounded: a hung server must not hold the arm at the pre-grasp for minutes
        except Exception as e: r, err = {"content": "", "timings": {}, "total_s": time.perf_counter() - t0}, "%s: %s" % (type(e).__name__, e)
        ans = (r.get("content") or "").strip(); tm = r.get("timings") or {}
        rec = {"ev": "gemma", "t": time.time(), "stage": stage, "kind": kind, "question": question, "answer": ans,
               "ms": int(round(r["total_s"] * 1000)), "tag": tag, "media": media,
               "prompt_n": tm.get("prompt_n"), "prompt_ms": tm.get("prompt_ms"), "predicted_n": tm.get("predicted_n"),
               "predicted_ms": tm.get("predicted_ms"), "cache_n": tm.get("cache_n")}
        if err: rec["error"] = err
        self.n += 1; self.on_record(rec)
        return ans.lower(), rec

    # --- the verified call types -------------------------------------------------------------
    def hear_colour(self, wav_bytes, stage="UNDERSTAND"):
        """Spoken order (any language) -> English colour word or None. voice_grab.py payload."""
        msgs = [{"role": "system", "content": HEAR_SYSTEM},
                {"role": "user", "content": [{"type": "text", "text": HEAR_Q}, audio_part(wav_bytes)]}]
        ans, rec = self.ask("hear_colour", HEAR_Q, msgs, 6, stage, media="audio")
        return colour_in(ans), ans, rec

    def crop_colour(self, crop_bgr, stage="LOCATE", media=None):
        """One detected can's crop -> one colour word. grab_loop.py / approach_can.py payload (no system prompt, no resize)."""
        msgs = [{"role": "user", "content": [image_part(crop_bgr, size=None), {"type": "text", "text": CROP_Q}]}]
        return self.ask("crop_colour", CROP_Q, msgs, 4, stage, media=media)

    def yesno(self, img_bgr, question, stage, media=None, system=None, tag=TAG):
        """Image + question after it -> True / False / None (unclear). grab_loop.py gemma_yesno payload."""
        q = question + " Answer with one word: yes or no."
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": [image_part(img_bgr), {"type": "text", "text": q}]}]
        ans, rec = self.ask("yesno", question, msgs, 3, stage, media=media, tag=tag)
        return (True if ans.startswith("yes") else False if ans.startswith("no") else None), ans, rec

    def heard_take_it(self, wav_bytes, stage="HANDOVER"):
        """2 s clip while holding the can out -> transcript; True if it contains a let-go phrase."""
        msgs = [{"role": "user", "content": [{"type": "text", "text": TAKE_Q}, audio_part(wav_bytes)]}]
        ans, rec = self.ask("take_it", TAKE_Q, msgs, 16, stage, media="audio")
        return any(w in ans for w in TAKE_WORDS), ans, rec

    def box(self, img_bgr, what, stage="LOCATE", media=None):
        """Gemma box_2d of `what` in the image's pixel coordinates, or None (the servo's cross-check fails on None). grab_loop.py gemma_box payload."""
        q = "Detect " + what + ". Output only JSON: [{\"box_2d\": [ymin, xmin, ymax, xmax], \"label\": \"can\"}] with coordinates normalized to 0-1000."
        msgs = [{"role": "user", "content": [image_part(img_bgr), {"type": "text", "text": q}]},
                {"role": "assistant", "content": "```json\n[\n  {\"box_2d\": ["}]
        ans, rec = self.ask("box", "Detect " + what, msgs, 24, stage, media=media, extra={"stop": ["]"]})
        nums = [int(n) for n in re.findall(r"\d+", ans[ans.rindex("[") + 1:] if "[" in ans else ans)][:4]
        if len(nums) != 4: return None, rec
        y1, x1, y2, x2 = nums
        H, W = img_bgr.shape[:2]                                            # the frame's own size (the head stream on PC2 need not be 640x480)
        return (x1 / 1000 * W, y1 / 1000 * H, x2 / 1000 * W, y2 / 1000 * H), rec

    def describe_crop(self, crop_bgr, stage="LOOK", media=None):
        """One detected can's crop -> a short description ("purple la croix", "chi sparkling water"), lowercase, at most 4 words."""
        msgs = [{"role": "system", "content": DESCRIBE_SYSTEM}, {"role": "user", "content": [image_part(crop_bgr, size=None), {"type": "text", "text": DESCRIBE_Q}]}]
        ans, rec = self.ask("describe", DESCRIBE_Q, msgs, 10, stage, media=media)
        words = [w for w in re.findall(r"[a-z0-9]+", ans) if w not in ("a", "an", "the", "of", "can", "this", "is", "it", "unknown", "brand", "colour", "color", "no", "not", "none", "fruit", "pictured", "visible", "drink", "soda")]
        return " ".join(words[:4]) or "unknown can", rec

    def hear_choice(self, wav_bytes, descriptions, stage="UNDERSTAND"):
        """Spoken order (any language) + the numbered descriptions in the system prompt -> index into descriptions, or None.
        Returns (index or None, raw answer, record); the answer is a number or none (max 4 tokens)."""
        cans = "; ".join("%d: %s" % (i + 1, d) for i, d in enumerate(descriptions))
        msgs = [{"role": "system", "content": CHOOSE_SYSTEM.format(cans=cans)},
                {"role": "user", "content": [{"type": "text", "text": CHOOSE_Q}, audio_part(wav_bytes)]}]
        ans, rec = self.ask("hear_choice", CHOOSE_Q, msgs, 4, stage, media="audio")
        m = re.search(r"\d+", ans); idx = int(m.group()) - 1 if m else None
        return (idx if idx is not None and 0 <= idx < len(descriptions) else None), ans, rec

    def warmup(self, img_bgr=None, stage="PREFLIGHT"):
        """One request that fills the cached prefix of the vision path (or a text turn without an image)."""
        if img_bgr is not None: return self.yesno(img_bgr, "Is anything visible in the image?", stage)[1:]
        msgs = [{"role": "system", "content": VISION_SYSTEM}, {"role": "user", "content": "Say ready. Answer with one word."}]
        return self.ask("warmup", "Say ready.", msgs, 3, stage)
