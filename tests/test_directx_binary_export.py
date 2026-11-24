"""DirectX バイナリ出力を expected/directx_binary の .x ファイルと比較する。

Compare DirectX binary exports with the .x files in expected/directx_binary.
"""

import struct
import zlib
from pathlib import Path

import bpy
import pytest


EXPECTED = Path(__file__).with_name("expected") / "directx_binary"


@pytest.fixture
def binary_triangle(scene):
    mesh = bpy.data.meshes.new("Binary export mesh")
    mesh.from_pydata([(0, 0, 0), (2, 0, 0), (0, 0, 4)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("Binary export triangle", mesh)
    scene.collection.objects.link(obj)


@pytest.mark.parametrize(
    ("minimum", "filename"),
    [(False, "triangle_full.x"), (True, "triangle_minimum.x")],
    ids=["full", "minimum"],
)
def test_binary_triangle(binary_triangle, tmp_path, minimum, filename):
    """三角形の通常出力と最小出力をバイト単位で確認する。

    Compare full and minimal triangle exports byte for byte.
    """
    path = tmp_path / filename
    assert bpy.ops.export.directx_x_for_bve(
        filepath=str(path), mode="binary", export_minimum=minimum
    ) == {"FINISHED"}
    assert path.read_bytes() == (EXPECTED / filename).read_bytes()


def test_binary_empty_selection(binary_triangle, tmp_path):
    """選択が空の場合に、件数がゼロのメッシュを出力することを確認する。

    Check that an empty selection produces a mesh with zero counts.
    """
    path = tmp_path / "empty_selection.x"
    assert bpy.ops.export.directx_x_for_bve(
        filepath=str(path),
        mode="binary",
        export_minimum=True,
        export_selected_only=True,
    ) == {"FINISHED"}
    assert path.read_bytes() == (EXPECTED / path.name).read_bytes()


def test_compressed_binary_triangle(binary_triangle, tmp_path):
    """圧縮ヘッダーと単一ブロックを確認し、展開結果を最小出力と比較する。

    Check the compressed header and single block, then compare the decompressed
    payload with the minimal binary export.
    """
    path = tmp_path / "triangle_compressed.x"
    assert bpy.ops.export.directx_x_for_bve(
        filepath=str(path), mode="binary_zip", export_minimum=True
    ) == {"FINISHED"}

    data = path.read_bytes()
    expected = (EXPECTED / "triangle_minimum.x").read_bytes()
    assert data[:16] == b"xof 0302bzip0032"
    total_size, block_size, compressed_size, magic = struct.unpack_from(
        "<IHH2s", data, 16
    )
    assert total_size == len(expected)
    assert block_size == len(expected) - 16
    assert compressed_size == len(data) - 24
    assert magic == b"CK"
    assert zlib.decompress(data[26:], wbits=-15) == expected[16:]
