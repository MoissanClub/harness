"""Vulkan check for the LiteRT-LM GPU run plan (hackathon/briefs/2026-10-21-litert-gpu.md), stdlib ctypes only: no vulkan-tools needed.
Loads libvulkan.so.1 (the library LiteRT-LM's WebGPU accelerator dlopens), creates an instance and lists the physical devices.
Prints one line per device and a verdict line; exit 0 only if a hardware GPU (integrated or discrete) is listed.
Usage: python3 -I vk_probe.py"""
import ctypes, ctypes.util, json, sys

TYPES = {0: "other", 1: "integrated GPU", 2: "discrete GPU", 3: "virtual GPU", 4: "CPU"}


def ver(v):
    return "%d.%d.%d" % (v >> 22 & 0x7F, v >> 12 & 0x3FF, v & 0xFFF)


class AppInfo(ctypes.Structure):  # VkApplicationInfo
    _fields_ = [("sType", ctypes.c_int), ("pNext", ctypes.c_void_p), ("pApplicationName", ctypes.c_char_p),
                ("applicationVersion", ctypes.c_uint32), ("pEngineName", ctypes.c_char_p), ("engineVersion", ctypes.c_uint32),
                ("apiVersion", ctypes.c_uint32)]


class InstanceInfo(ctypes.Structure):  # VkInstanceCreateInfo
    _fields_ = [("sType", ctypes.c_int), ("pNext", ctypes.c_void_p), ("flags", ctypes.c_uint32), ("pApplicationInfo", ctypes.POINTER(AppInfo)),
                ("enabledLayerCount", ctypes.c_uint32), ("ppEnabledLayerNames", ctypes.c_void_p),
                ("enabledExtensionCount", ctypes.c_uint32), ("ppEnabledExtensionNames", ctypes.c_void_p)]


def probe():
    names = ["libvulkan.so.1", "libvulkan.so", ctypes.util.find_library("vulkan")]
    lib, errs = None, []
    for n in [x for x in names if x]:
        try:
            lib = ctypes.CDLL(n); break
        except OSError as e:
            errs.append(str(e))
    if lib is None:
        return {"ok": False, "verdict": "NO LIBVULKAN: libvulkan.so.1 not loadable (%s)" % "; ".join(errs), "devices": []}
    app = AppInfo(0, None, b"vk_probe", 1, b"none", 1, (1 << 22) | (1 << 12))  # Vulkan 1.1
    info = InstanceInfo(1, None, 0, ctypes.pointer(app), 0, None, 0, None)
    inst = ctypes.c_void_p()
    lib.vkCreateInstance.restype = ctypes.c_int
    r = lib.vkCreateInstance(ctypes.byref(info), None, ctypes.byref(inst))
    if r != 0:
        return {"ok": False, "verdict": "NO INSTANCE: vkCreateInstance returned %d (no ICD? check /etc/vulkan/icd.d and /usr/share/vulkan/icd.d)" % r, "devices": []}
    n = ctypes.c_uint32(0)
    lib.vkEnumeratePhysicalDevices(inst, ctypes.byref(n), None)
    devs = (ctypes.c_void_p * max(n.value, 1))()
    lib.vkEnumeratePhysicalDevices(inst, ctypes.byref(n), devs)
    out = []
    for i in range(n.value):
        buf = ctypes.create_string_buffer(4096)  # VkPhysicalDeviceProperties is ~830 bytes; only the head is read
        lib.vkGetPhysicalDeviceProperties(ctypes.c_void_p(devs[i]), buf)
        api, drv, vendor, dev_id, dtype = (int.from_bytes(buf.raw[o:o + 4], "little") for o in (0, 4, 8, 12, 16))
        name = buf.raw[20:276].split(b"\0", 1)[0].decode(errors="replace")
        out.append({"name": name, "type": TYPES.get(dtype, str(dtype)), "api": ver(api), "vendor": hex(vendor), "device_id": hex(dev_id)})
    lib.vkDestroyInstance(inst, None)
    hw = [d for d in out if d["type"] in ("integrated GPU", "discrete GPU")]
    if hw:
        verdict = "VULKAN OK: %s (%s, Vulkan %s)" % (hw[0]["name"], hw[0]["type"], hw[0]["api"])
    elif out:
        verdict = "SOFTWARE ONLY: %s is not a GPU (llvmpipe-like): LiteRT's GPU mode would run on the CPU or fail" % out[0]["name"]
    else:
        verdict = "NO DEVICE: an instance but no physical device"
    return {"ok": bool(hw), "verdict": verdict, "devices": out}


if __name__ == "__main__":
    res = probe()
    for d in res["devices"]:
        print("device: %(name)s | %(type)s | Vulkan %(api)s | vendor %(vendor)s" % d)
    print(res["verdict"])
    print(json.dumps(res))
    sys.exit(0 if res["ok"] else 1)
