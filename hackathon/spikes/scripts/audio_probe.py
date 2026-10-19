import socket, struct, time, wave, array, sys
from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient

IFACE, LOCAL_IP = "enP8p1s0", "192.168.123.164"
ChannelFactoryInitialize(0, IFACE)
ac = AudioClient(); ac.SetTimeout(10.0); ac.Init()
print("volume:", ac.GetVolume(), flush=True)
msgs = []
sub = ChannelSubscriber("rt/audio_msg", String_); sub.Init(lambda m: msgs.append(m.data), 10)
print("tts code:", ac.TtsMaker("Audio test. One, two, three. Please say a sentence now.", 1), flush=True)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("", 5555))
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                struct.pack("4s4s", socket.inet_aton("239.168.123.161"), socket.inet_aton(LOCAL_IP)))
sock.settimeout(1.0)
pcm, pkts, sizes, t0 = bytearray(), 0, set(), time.time()
while time.time() - t0 < 12:
    try:
        d, _ = sock.recvfrom(16384); pcm += d; pkts += 1; sizes.add(len(d))
    except socket.timeout:
        pass
print(f"mic multicast: packets={pkts} bytes={len(pcm)} sizes={sorted(sizes)} seconds={len(pcm)/32000:.1f}")
if pcm:
    with wave.open("/home/unitree/spike/mic_capture.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(pcm))
    a = array.array("h", bytes(pcm[: len(pcm) // 2 * 2]))
    print("peak abs sample:", max(abs(x) for x in a), "(of 32767)")
print("rt/audio_msg messages:", len(msgs))
for m in msgs[:6]:
    print("  ", m[:240])
