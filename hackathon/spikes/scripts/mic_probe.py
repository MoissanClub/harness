import socket, struct, time, wave, array, json
from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient

IFACE, LOCAL_IP = "enP8p1s0", "192.168.123.164"
ChannelFactoryInitialize(0, IFACE)
ac = AudioClient(); ac.SetTimeout(10.0); ac.Init()
msgs = []
sub = ChannelSubscriber("rt/audio_msg", String_); sub.Init(lambda m: msgs.append(m.data), 10)
# community-reported voice API 1008: mic/asr mode on
try:
    print("api 1008 mode=1 ->", ac._Call(1008, json.dumps({"mode": 1})), flush=True)
except Exception as e:
    print("api 1008 failed:", e, flush=True)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("", 5555))
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                struct.pack("4s4s", socket.inet_aton("239.168.123.161"), socket.inet_aton(LOCAL_IP)))
sock.settimeout(1.0)
pcm, pkts, sizes, t0, first = bytearray(), 0, set(), time.time(), None
while time.time() - t0 < 12:
    try:
        d, _ = sock.recvfrom(16384); pcm += d; pkts += 1; sizes.add(len(d))
        if first is None: first = time.time() - t0
    except socket.timeout:
        pass
print(f"mic multicast: packets={pkts} bytes={len(pcm)} sizes={sorted(sizes)} seconds={len(pcm)/32000:.1f} first_packet_at={first}")
if pcm:
    with wave.open("/home/unitree/spike/mic_capture.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(pcm))
    a = array.array("h", bytes(pcm[: len(pcm) // 2 * 2]))
    print("peak abs sample:", max(abs(x) for x in a), "rms:", int((sum(x*x for x in a)/len(a))**0.5))
print("rt/audio_msg messages:", len(msgs))
for m in msgs[:8]:
    print("  ", m[:240])
