"""引导脚本：仅针对 Python 3.10+ 的新框架反编译器（py310~py314）运行 selftest。

完全依赖新框架（pyXXDecompiler 文件夹），不调用旧 `pyvers`、`bytecode2code`。
"""
import subprocess, sys, os
os.chdir(r"D:\py\bytecode2code")

def run(version: str):
    interpreter = os.path.join("embed_python", "python-" + version, "python.exe")
    if not os.path.isfile(interpreter):
        print("SKIP %s (no interpreter)" % version)
        return
    cmd = [interpreter, "-m", "tests.selftest", "--all"]
    print("=" * 50)
    print("RUNNING %s via %s" % (version, interpreter))
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    # 输出中只保留本版本行
    for line in proc.stdout.splitlines():
        if line.startswith("== Python") or ("FAIL" in line) or ("ok" in line) or ("passed" in line):
            print(line)
    if proc.returncode != 0:
        print("FAILED (exit %d)" % proc.returncode)

for v in ("3.10", "3.11", "3.12", "3.13", "3.14"):
    run(v)
