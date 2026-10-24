import math
from math import gcd
import os
try:
    from docx import Document
    from docx.shared import Inches
    docx_support = True
except ImportError:
    docx_support = False

class ReciprocalAnalyzer:

    def __init__(self, x):
        self.x = x
        self._validate_input()
        self.a, self.b = self._convert_to_fraction()
        self.non_repeating = self._get_non_repeating_part()
        self.repeating = self._get_repeating_part()

    def _validate_input(self):
        if self.x == 0:
            raise ValueError('输入不能为0')
        if isinstance(self.x, float):
            try:
                str_x = str(self.x).rstrip('0').rstrip('.') if '.' in str(self.x) else str(self.x)
                if 'e' in str_x:
                    raise ValueError('不支持非有限小数或高精度浮点数')
            except:
                raise ValueError('仅支持整数或有限小数输入')
        raise ValueError('仅支持整数或有限小数输入')

    def _convert_to_fraction(self):
        if isinstance(self.x, float):
            s = str(self.x).split('.')
            integer_part = s[0] if s[0] else '0'
            decimal_part = s[1].rstrip('0') if len(s) > 1 else ''
            d = len(decimal_part)
            denominator = int(integer_part) * 10 ** d + (int(decimal_part) if d > 0 else 0)
            numerator = 10 ** d
        else:
            numerator, denominator = (1, int(self.x))
        common_divisor = gcd(numerator, denominator)
        a = numerator // common_divisor
        b = denominator // common_divisor
        return (a, b)

    def _prime_factorization_25(self, n):
        m, n5 = (0, 0)
        while n % 2 == 0:
            m += 1
            n = n // 2
        while n % 5 == 0:
            n5 += 1
            n = n // 5
        return (m, n5, n)

    def _get_non_repeating_part(self):
        m, n5, _ = self._prime_factorization_25(self.b)
        max_exp = max(m, n5)
        if max_exp == 0:
            return ''
        factor = 10 ** max_exp
        integer_part = self.a * factor // self.b
        non_rep_str = str(integer_part).zfill(max_exp)
        return non_rep_str[-max_exp:] if len(non_rep_str) > max_exp else non_rep_str

    def _get_repeating_part(self):
        m, n5, k = self._prime_factorization_25(self.b)
        if k == 1:
            return ''
        max_exp = max(m, n5)
        a_prime = self.a * 10 ** max_exp % self.b
        remainder_map = {}
        repeating_digits = []
        current_remainder = a_prime
        while current_remainder not in remainder_map:
            remainder_map[current_remainder] = len(repeating_digits)
            current_remainder *= 10
            digit = current_remainder // k
            repeating_digits.append(str(digit))
            current_remainder = current_remainder % k
            if current_remainder == 0:
                return ''
        cycle_start = remainder_map[current_remainder]
        return ''.join(repeating_digits[cycle_start:])

    def get_cyclic_string(self):
        if not self.repeating:
            return f'0.{self.non_repeating}' if self.non_repeating else '1.0'
        if len(self.repeating) == 1:
            cyclic = f'{self.repeating}˙'
        else:
            cyclic = f'˙{self.repeating}˙'
        return f'0.{self.non_repeating}{cyclic}' if self.non_repeating else f'0.{cyclic}'

    def get_results(self):
        return (self.non_repeating, self.repeating)

    def __str__(self):
        non_rep, rep = self.get_results()
        return f"1/{self.x} → 不循环: '{non_rep}', 循环: '{rep}'"

def write_txt(filename, results):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(results))
        return (True, f'结果已成功保存到：{os.path.abspath(filename)}')
    except Exception as e:
        return (False, f'TXT文件保存失败: {e}')

def write_docx(filename, results):
    if not docx_support:
        return (False, '缺少python-docx库，无法生成DOCX文件（可通过 pip install python-docx 安装）')
    try:
        doc = Document()
        doc.add_heading(results[0], level=1)
        doc.add_paragraph(results[1])
        for line in results[2:-1]:
            doc.add_paragraph(line)
        doc.add_paragraph(results[-1])
        doc.save(filename)
        return (True, f'结果已成功保存到：{os.path.abspath(filename)}')
    except Exception as e:
        return (False, f'DOCX文件保存失败: {e}')

def write_doc(filename, results):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(results))
        return (True, f'DOC文件（兼容TXT格式）已保存到：{os.path.abspath(filename)}（提示：DOC为旧格式，建议优先使用DOCX/TXT）')
    except Exception as e:
        return (False, f'DOC文件保存失败: {e}')