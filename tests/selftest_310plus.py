"""引导脚本：只对新框架（``pyXXDecompiler`` 文件夹）跑 3.10+ 的 selftest。

等价于 ``python -m tests.selftest --all``，但逐版本单独输出，方便只看某一组。
``tests/selftest.py`` 自己会把仓库根目录放进 ``sys.path``，所以这里按脚本路径
调用它，而不是 ``-m tests.selftest`` -- 嵌入式发行版不把工作目录放进
``sys.path``，用 ``-m`` 只会得到 ``ModuleNotFoundError: No module named 'tests'``。
"""
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)

SELFTEST = os.path.join(_ROOT, "tests", "selftest.py")


def run(version: str) -> int:
    interpreter = os.path.join(
        _ROOT, "embed_python", "python-" + version, "python.exe")
    if not os.path.isfile(interpreter):
        print("SKIP %s (no interpreter)" % version)
        return 0
    print("=" * 50)
    print("RUNNING %s via %s" % (version, os.path.relpath(interpreter, _ROOT)))
    proc = subprocess.run([interpreter, SELFTEST],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    for line in proc.stdout.splitlines():
        print(line)
    if proc.returncode != 0:
        print("FAILED (exit %d)" % proc.returncode)
        print(proc.stderr)
    return proc.returncode


def main() -> int:
    versions = sys.argv[1:] or ("3.10", "3.11", "3.12", "3.13", "3.14", "3.15")
    return max((run(version) for version in versions), default=0)


if __name__ == "__main__":
    sys.exit(main())
