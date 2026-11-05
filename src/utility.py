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


class ByteBufferError(Exception):
    pass


# Java風ByteBuffer / Java-like ByteBuffer
class ByteBuffer:
    def __init__(self, data):
        self.array = bytearray(data)
        self.pos = 0

    def _check(self, n):
        if self.pos + n > len(self.array):
            raise ByteBufferError("Unexpected end of file")

    def get_next(self):
        self._check(1)
        value = self.array[self.pos]
        self.pos += 1
        return value

    def get_length(self, length):
        self._check(length)
        value = self.array[self.pos : self.pos + length]
        self.pos += length
        return value

    def get_int(self):
        self._check(4)
        # struct.unpack_fromはスライスコピーが発生しない / No slice copy with struct.unpack_from
        value = struct.unpack_from("<I", self.array, self.pos)[0]
        self.pos += 4
        return value

    def get_short(self):
        self._check(2)
        value = struct.unpack_from("<H", self.array, self.pos)[0]
        self.pos += 2
        return value

    def get_float(self):
        self._check(4)
        value = struct.unpack_from("<f", self.array, self.pos)[0]
        self.pos += 4
        return value

    def get_double(self):
        self._check(8)
        value = struct.unpack_from("<d", self.array, self.pos)[0]
        self.pos += 8
        return value

    def get_int_list(self, count):
        if count < 0:
            raise ByteBufferError("Invalid integer list length")
        self._check(count * 4)
        # 一括で読み込む / Read in bulk
        values = struct.unpack_from("<%dI" % count, self.array, self.pos)
        self.pos += count * 4
        return values

    def get_float_list(self, count, size):
        if count < 0:
            raise ByteBufferError("Invalid float list length")
        self._check(count * size)
        # 一括で読み込む / Read in bulk
        if size == 8:
            values = struct.unpack_from("<%dd" % count, self.array, self.pos)
        else:
            values = struct.unpack_from("<%df" % count, self.array, self.pos)
        self.pos += count * size
        return values

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
