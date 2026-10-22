def write_txt(filename, results):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(results))
        return True, "ok"
    except Exception as e:
        return False, "fail"
