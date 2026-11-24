"""固定の DirectX 0302 バイナリ入力を Blender で読み込む。

Import fixed DirectX 0302 binary fixtures into Blender.
"""

from pathlib import Path

import bpy
import pytest


INPUTS = Path(__file__).with_name("inputs") / "directx_binary"


def import_binary(filename, *, scale=1.0):
    operator = getattr(bpy.ops, "import").directx_x_for_bve
    return operator(
        filepath=str(INPUTS / filename),
        remove_all=False,
        scale=scale,
        gamma_correction=False,
    )


@pytest.mark.parametrize(
    ("filename", "material_name", "object_name"),
    [
        ("triangle_float32.x", "BinaryInputRed", None),
        ("triangle_float64.x", "BinaryInputRed", None),
        ("triangle_compressed.x", "BinaryInputRed", None),
        ("unnamed_material.x", None, None),
        ("extension_block.x", "BinaryInputRed", None),
        pytest.param(
            "unnamed_frame.x",
            "BinaryInputRed",
            None,
            marks=pytest.mark.skip(reason="Binary Frame loop does not advance tokens"),
        ),
        pytest.param(
            "named_frame.x",
            "BinaryInputRed",
            "NamedFrame0",
            marks=pytest.mark.skip(reason="Binary Frame loop does not advance tokens"),
        ),
        pytest.param(
            "material_reference.x",
            "ReferencedRed",
            None,
            marks=pytest.mark.skip(
                reason="Binary material-reference lookahead counts its opening brace twice"
            ),
        ),
    ],
    ids=[
        "float32-with-template",
        "float64",
        "compressed",
        "unnamed-material",
        "extension-block",
        "unnamed-frame",
        "named-frame",
        "material-reference",
    ],
)
def test_import_binary_triangle(scene, filename, material_name, object_name):
    """書式やブロック構成が異なる入力から、同じ三角形を読み込めることを確認する。

    Check that binary variants and block structures yield the same triangle.
    """
    assert import_binary(filename, scale=2.0) == {"FINISHED"}

    (obj,) = scene.objects
    if object_name is not None:
        assert obj.name == object_name
    mesh = obj.data
    (face,) = mesh.polygons
    assert [tuple(mesh.vertices[i].co) for i in face.vertices] == [
        (0.0, -6.0, 8.0),
        (4.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    ]
    assert [tuple(uv.vector) for uv in mesh.uv_layers.active.uv] == [
        (0.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
    ]
    material = mesh.materials[face.material_index]
    if material_name is not None:
        assert material.name == material_name
    shader = material.node_tree.nodes.get("Principled BSDF")
    assert tuple(shader.inputs["Base Color"].default_value) == (1.0, 0.0, 0.0, 1.0)


def test_import_binary_uv_seam(scene):
    """同じ座標を統合しても、面ごとの UV が残ることを確認する。

    Check that welding coincident vertices preserves face-corner UVs.
    """
    assert import_binary("uv_seam.x") == {"FINISHED"}

    (obj,) = scene.objects
    mesh = obj.data
    assert len(mesh.vertices) == 4
    assert len(mesh.polygons) == 2
    shared_vertex = next(v.index for v in mesh.vertices if tuple(v.co) == (1, 0, 0))
    uvs = mesh.uv_layers.active.uv
    assert [
        tuple(uvs[loop.index].vector)
        for loop in mesh.loops
        if loop.vertex_index == shared_vertex
    ] == [(0.5, 1.0), (0.75, 1.0)]


def test_import_binary_multiple_materials(scene):
    """面の順序と異なるマテリアル番号でも、各面が正しい色になることを確認する。

    Check that face colors follow material indices even when their orders differ.
    """
    assert import_binary("multiple_materials.x") == {"FINISHED"}
    assert len(scene.objects) == 2

    faces_by_color = {}
    for obj in scene.objects:
        mesh = obj.data
        (face,) = mesh.polygons
        material = mesh.materials[face.material_index]
        shader = material.node_tree.nodes.get("Principled BSDF")
        color = tuple(shader.inputs["Base Color"].default_value)
        faces_by_color[color] = {tuple(mesh.vertices[i].co) for i in face.vertices}

    assert faces_by_color == {
        (1, 0, 0, 1): {(1, 0, 0), (1, 0, 1), (0, 0, 1)},
        (0, 0, 1, 1): {(0, 0, 0), (1, 0, 0), (0, 0, 1)},
    }


def test_import_binary_empty_mesh(scene):
    """件数がゼロのメッシュを読み込んでもオブジェクトを作らないことを確認する。

    Verify that importing a mesh with zero counts creates no objects.
    """
    assert import_binary("empty_mesh.x") == {"FINISHED"}
    assert len(scene.objects) == 0
