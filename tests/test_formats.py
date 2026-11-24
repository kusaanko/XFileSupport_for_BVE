import struct

import bpy
import pytest

from src.utility import ByteBuffer, float_to_str


VERTICES = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 4.0)]


@pytest.fixture
def triangle(scene):
    mesh = bpy.data.meshes.new("Triangle")
    mesh.from_pydata(VERTICES, [], [(0, 1, 2)])
    obj = bpy.data.objects.new("Triangle", mesh)
    scene.collection.objects.link(obj)
    return obj


@pytest.mark.parametrize(
    ("mode", "header"),
    [
        ("text", b"xof 0302txt 0032"),
        ("binary", b"xof 0302bin 0032"),
        ("binary_zip", b"xof 0302bzip0032"),
    ],
)
def test_directx_round_trip(tmp_path, triangle, scene, mode, header):
    path = tmp_path / "triangle.x"
    assert bpy.ops.export.directx_x_for_bve(filepath=str(path), mode=mode) == {
        "FINISHED"
    }
    assert path.read_bytes()[:16] == header

    importer = getattr(bpy.ops, "import").directx_x_for_bve
    assert importer(filepath=str(path), remove_all=False) == {"FINISHED"}
    (imported,) = [obj for obj in scene.objects if obj != triangle]
    assert imported.type == "MESH"
    assert sorted(tuple(vertex.co) for vertex in imported.data.vertices) == sorted(
        VERTICES
    )
    (face,) = imported.data.polygons
    assert len(face.vertices) == 3
    assert set(face.vertices) == {0, 1, 2}


@pytest.mark.parametrize(
    ("operator_name", "options", "face_command", "extra_command"),
    [
        ("csv_for_bve", {}, "AddFace", "GenerateNormals"),
        (
            "csv_for_open_bve",
            {"use_add_face2": True},
            "AddFace2",
            "SetEmissiveColor,0,0,0",
        ),
    ],
)
def test_csv_triangle(
    tmp_path, triangle, operator_name, options, face_command, extra_command
):
    path = tmp_path / "triangle.csv"
    export = getattr(bpy.ops.export, operator_name)
    assert export(filepath=str(path), scale=2.0, **options) == {"FINISHED"}

    lines = path.read_text(encoding="ascii").splitlines()
    assert lines[0] == "CreateMeshBuilder,"
    vertices = [line.split(",")[1:] for line in lines if line.startswith("AddVertex,")]
    assert [tuple(map(float, vertex[:3])) for vertex in vertices] == [
        (0.0, 8.0, 6.0),
        (4.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    ]
    assert f"{face_command},0,1,2" in lines
    assert extra_command in lines
    if operator_name == "csv_for_open_bve":
        for vertex in vertices:
            assert tuple(map(float, vertex[3:])) == pytest.approx((0.0, 0.6, -0.8))


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1.25, "1.250000"), (-1e-7, "-0.0000001")],
)
def test_float_to_str(value, expected):
    assert float_to_str(value) == expected


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="Positive exponents lose one zero"
)
def test_float_to_str_preserves_large_positive_exponent():
    assert float_to_str(1e20) == "100000000000000000000.000000"


def test_byte_buffer_reads_little_endian_values_in_order():
    buffer = ByteBuffer(struct.pack("<BHIfd", 0xAA, 0x1234, 0x89ABCDEF, -1.25, 0.125))

    assert buffer.get_next() == 0xAA
    assert buffer.get_short() == 0x1234
    assert buffer.get_int() == 0x89ABCDEF
    assert buffer.get_float() == -1.25
    assert buffer.remaining() == 8
    assert buffer.get_double() == 0.125
    assert not buffer.has_remaining()
