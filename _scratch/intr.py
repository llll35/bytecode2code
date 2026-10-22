import dis
print("intrinsic_1_descs" in dir(dis), getattr(dis, "intrinsic_1_descs", None))
print(getattr(dis, "_intrinsic_1_descs", None))
