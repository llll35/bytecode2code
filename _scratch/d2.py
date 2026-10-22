def g(n):
    while True:
        try:
            parts = n.split(",")
            break
        except ValueError as e:
            print(e)
    results = []
    for i in results:
        try:
            print(i)
        except KeyError as e:
            print(e)
    return results
