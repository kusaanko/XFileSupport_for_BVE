"""BVE・OpenBVE 向け CSV の出力全文を固定の期待値と比較する。

Compare complete BVE and OpenBVE CSV exports with fixed fixtures.
"""

from pathlib import Path

import bpy
import pytest


EXPECTED = Path(__file__).with_name("expected") / "csv"


@pytest.fixture
def textured_triangle(scene):
    mesh = bpy.data.meshes.new("CSV mesh")
    mesh.from_pydata([(0, 0, 0), (2, 0, 0), (0, 0, 4)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("CSV triangle", mesh)
    scene.collection.objects.link(obj)

    material = bpy.data.materials.new("CSV material")
    material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.new("CSV texture", width=1, height=1)
    texture.image.filepath = "//csv_texture.png"
    texture.extension = "EXTEND"
    shader = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    mesh.materials.append(material)
    uv_layer = mesh.uv_layers.new()
    for loop_uv, uv in zip(uv_layer.uv, [(0, 0), (1, 0), (0, 1)], strict=True):
        loop_uv.vector = uv


@pytest.mark.parametrize(
    ("operator_name", "filename", "options"),
    [
        ("csv_for_bve", "bve_textured_triangle.csv", {}),
        ("csv_for_open_bve", "openbve_textured_triangle.csv", {"use_add_face2": True}),
    ],
    ids=["bve", "openbve"],
)
def test_csv_textured_triangle(
    textured_triangle, tmp_path, operator_name, filename, options
):
    """座標・面・テクスチャ・UV と、形式別のコマンドを確認する。

    Check geometry, texture, UVs, and commands specific to each CSV dialect.
    """
    output = tmp_path / filename
    export = getattr(bpy.ops.export, operator_name)
    assert export(filepath=str(output), **options) == {"FINISHED"}
    assert output.read_text(encoding="ascii") == (EXPECTED / filename).read_text(
        encoding="ascii"
    )


@pytest.mark.parametrize("operator_name", ["csv_for_bve", "csv_for_open_bve"])
def test_csv_empty_selection(textured_triangle, tmp_path, operator_name):
    """未選択のメッシュがある状態で、選択対象だけの出力が空になることを確認する。

    Check that selected-only export writes an empty file with no selected objects.
    """
    output = tmp_path / "empty.csv"
    export = getattr(bpy.ops.export, operator_name)
    assert export(filepath=str(output), export_selected_only=True) == {"FINISHED"}
    assert output.read_bytes() == b""
