import struct


def vertex_to_str(vertex):
    # Blender X Z Y
    # DirectX X Y Z
    return (
        float_to_str(round(vertex[0], 10))
        + ";"
        + float_to_str(round(vertex[2], 10))
        + ";"
        + float_to_str(round(vertex[1], 10))
    )


def vertex_to_str_csv(vertex):
    # Blender X Z Y
    # DirectX X Y Z
    return (
        float_to_str(round(vertex[0], 10))
        + ","
        + float_to_str(round(vertex[2], 10))
        + ","
        + float_to_str(round(vertex[1], 10))
    )


# expを使用しないstrにする / Convert float to string without using exp
def float_to_str(f):
    float_string = repr(f)
    if "e" in float_string:  # 指数表記を検知 / detect scientific notation
        digits, exp = float_string.split("e")
        digits = digits.replace(".", "").replace("-", "")
        exp = int(exp)
        zero_padding = (
            "0" * (abs(int(exp)) - 1)
        )  # sci 表記における小数点以下のマイナス1 / minus 1 for decimal point in the sci notation
        sign = "-" if f < 0 else ""
        if exp > 0:
            float_string = "{}{}{}.0".format(sign, digits, zero_padding)
        else:
            float_string = "{}0.{}{}".format(sign, zero_padding, digits)
    length = len(float_string[float_string.find(".") + 1 :])
    if length < 6:
        float_string = float_string + ("0" * (6 - length))
    return float_string


# Java風ByteBuffer / Java-like ByteBuffer
class ByteBuffer:
    def __init__(self, data):
        self.array = bytearray(data)
        self.pos = 0

    def get_next(self):
        value = self.array[self.pos]
        self.pos += 1
        return value

    def get_length(self, length):
        value = self.array[self.pos : self.pos + length]
        self.pos += length
        return value

    def get_int(self):
        return int.from_bytes(self.get_length(4), byteorder="little")

    def get_short(self):
        return int.from_bytes(self.get_length(2), byteorder="little")

    def get_float(self):
        return struct.unpack("<f", self.get_length(4))[0]

    def get_double(self):
        return struct.unpack("<d", self.get_length(8))[0]

    def has_remaining(self):
        return len(self.array) > self.pos

    def append(self, data):
        self.array.extend(data)

    def write(self, data):
        self.array.extend(data)

    def skip(self, length):
        self.pos += length

    def length(self):
        return len(self.array)

    def remaining(self):
        return len(self.array) - self.pos
