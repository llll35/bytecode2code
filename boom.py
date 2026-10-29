def ultimate_cf_nightmare(data, trigger):
    result = []
    
    # [攻击点 1] for-else 结构 (针对 D4 缺陷)
    for idx, val in enumerate(data):
        
        # [攻击点 2] 多上下文管理器 (针对多 with + return/控制流 崩溃)
        with open("x") as f1, open("y") as f2:
            
            try:
                # [攻击点 3] try 块内的 break/continue (针对 D2 缺陷)
                if val == 'skip':
                    continue
                if val == 'stop':
                    break
                
                # [攻击点 4] except as 隐式清理 + 嵌套 finally
                try:
                    result.append(int(val))
                except ValueError as e:
                    result.append(str(e))
                    # 在 except 中 continue：handler 回边与 continue 同形
                    continue 
                finally:
                    # [攻击点 5] 3层嵌套 finally (针对 D3 缺陷)
                    try:
                        if trigger:
                            pass
                    finally:
                        try:
                            result.append("deep")
                        finally:
                            result.append("deepest")
            finally:
                result.append("mid")
                
    else:
        # [攻击点 1 延续] 循环正常结束时的 else
        # 字节码上，如果没有 break，else 块和循环后的代码完全无法区分
        result.append("finished")
        
    # [攻击点 6] 函数末尾的 try/finally return (针对 try 体末尾 return 丢失)
    try:
        return result
    finally:
        result.append("cleanup")