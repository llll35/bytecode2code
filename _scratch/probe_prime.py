import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.cases import SAMPLES, OUTPUTS
from tests.test_ast import report

r = report("prime")
print("\n".join(r.diff))