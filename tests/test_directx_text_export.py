"""Blender の DirectX テキスト出力を実行し、生成した .x ファイルの全文を比較する。
期待値は expected/directx_text に置く。読み込み時に改行コードを統一し、
Windows と Unix で同じ期待値を使う。

Exercise Blender's DirectX text exporter and compare complete .x files.

Expected files live in expected/directx_text. Text reads normalize line endings
so Windows and Unix exports can use the same fixtures.
"""

from pathlib import Path

import bpy
import pytest


EXPECTED = Path(__file__).with_name("expected") / "directx_text"


def add_mesh(scene, vertices, face):
    mesh = bpy.data.meshes.new("Text export mesh")
    mesh.from_pydata(vertices, [], [face])
    obj = bpy.data.objects.new("Text export object", mesh)
    scene.collection.objects.link(obj)
    return obj


def assert_text_export(path, expected_file, **options):
    assert bpy.ops.export.directx_x_for_bve(
        filepath=str(path), mode="text", **options
    ) == {"FINISHED"}
    assert path.read_text(encoding="ascii") == (EXPECTED / expected_file).read_text(
        encoding="ascii"
    )


@pytest.mark.parametrize("minimum", [False, True], ids=["full", "minimum"])
def test_text_triangle_sections(scene, tmp_path, minimum):
    """テンプレート付きの通常出力と最小出力で、三角形の形状、法線、既定の UV を確認する。
    通常出力は triangle_full.x、最小出力は triangle_minimum.x と比較する。

    Check triangle geometry, normals, and default UVs with and without templates.

    Compare against triangle_full.x or triangle_minimum.x, respectively.
    """
    add_mesh(scene, [(0, 0, 0), (-2, 0, 0), (0, 3, 4)], (0, 1, 2))
    expected_file = "triangle_minimum.x" if minimum else "triangle_full.x"
    assert_text_export(tmp_path / "triangle.x", expected_file, export_minimum=minimum)


def test_text_selected_quad_preserves_face_and_uvs(scene, tmp_path):
    """選択した四角形だけを出力し、selected_quad.x と比較する。
    面が四角形のままか、移動とスケールが反映されるか、テクスチャ名と
    V 座標の反転が正しいかを確認する。

    Compare against selected_quad.x after exporting only the selected quad.

    The fixture checks the four-corner face, world translation, export scale,
    texture filename, and inverted V coordinates.
    """
    quad = add_mesh(scene, [(0, 0, 0), (2, 0, 0), (2, 3, 0), (0, 3, 0)], (0, 1, 2, 3))
    material = bpy.data.materials.new("Test material")
    material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.new("Test texture", width=1, height=1)
    texture.image.filepath = "//test_texture.png"
    shader = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    quad.data.materials.append(material)

    uv_layer = quad.data.uv_layers.new()
    for loop_uv, uv in zip(uv_layer.uv, [(0, 0), (1, 0), (1, 1), (0, 1)], strict=True):
        loop_uv.vector = uv
    quad.location.x = -1
    quad.select_set(True)
    add_mesh(scene, [(10, 0, 0), (12, 0, 0), (10, 3, 0)], (0, 1, 2))

    assert_text_export(
        tmp_path / "quad.x",
        "selected_quad.x",
        export_selected_only=True,
        scale=2.0,
        export_minimum=True,
    )


def test_text_export_rejects_other_extension(scene, tmp_path):
    """拡張子が .x 以外なら出力を中止し、既存ファイルの内容を保持することを確認する。

    Reject a non-.x destination and preserve its existing contents.
    """
    path = tmp_path / "mesh.txt"
    path.write_bytes(b"existing file")

    result = bpy.ops.export.directx_x_for_bve(filepath=str(path), mode="text")

    assert result == {"CANCELLED"}
    assert path.read_bytes() == b"existing file"


def test_text_empty_selection_keeps_zero_counts(scene, tmp_path):
    """選択が空のときに empty_selection.x と比較し、各メッシュ項目の件数が
    0 として出力されることを確認する。

    Compare against empty_selection.x to check all zero-count mesh sections.
    """
    add_mesh(scene, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], (0, 1, 2))
    assert_text_export(
        tmp_path / "empty.x",
        "empty_selection.x",
        export_selected_only=True,
        export_minimum=True,
    )
