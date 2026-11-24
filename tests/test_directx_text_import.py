"""手書きの .x 入力から Blender に読み込まれたメッシュを確認する。

Check meshes imported into Blender from hand-written text .x fixtures.
"""

from pathlib import Path

import bpy
import pytest


INPUTS = Path(__file__).with_name("inputs") / "directx_text"


def import_text(filename, *, scale=1.0):
    operator = getattr(bpy.ops, "import").directx_x_for_bve
    return operator(
        filepath=str(INPUTS / filename),
        remove_all=False,
        scale=scale,
        gamma_correction=False,
    )


@pytest.mark.parametrize(
    ("filename", "frame_name"),
    [
        ("triangle.x", None),
        ("comments.x", None),
        ("templates.x", None),
        ("mixed_separators.x", None),
        ("unnamed_frame.x", None),
        ("named_frame.x", "NamedFrame0"),
        ("unnamed_material.x", None),
        ("compact_exponents.x", None),
        ("extension_block.x", None),
    ],
    ids=[
        "plain",
        "comments",
        "templates",
        "mixed-separators",
        "unnamed-frame",
        "named-frame",
        "unnamed-material",
        "compact-exponents",
        "extension-block",
    ],
)
def test_import_triangle(scene, filename, frame_name):
    """三角形の軸変換、倍率、頂点順、UV の V 反転、マテリアルを確認する。

    コメントやテンプレート宣言を含む入力でも、同じ三角形になることを確認する。
    区切り文字のカンマとセミコロンが混在する入力も確認する。
    空の無名 Frame に続く無名 Frame から三角形を1つ読み込めることを確認する。
    名前付き Frame では、その名前がオブジェクト名に使われることも確認する。
    無名 Material でも面にマテリアルが割り当てられ、色が保持されることを確認する。
    指数表記を使った詰めた書式や、入れ子の拡張ブロックに続くメッシュも確認する。

    Check axis conversion, scale, winding, flipped V coordinates, and material
    with plain input, comments, template declarations, or mixed separators.
    Also check that an empty unnamed Frame followed by another unnamed Frame
    yields the single triangle inside the second frame.
    For a named Frame, verify that its name is used for the Blender object.
    For an unnamed Material, verify that the face receives its material color.
    Also cover compact scientific notation and a mesh after a nested extension block.
    """
    assert import_text(filename, scale=2.0) == {"FINISHED"}

    (obj,) = scene.objects
    if frame_name is not None:
        assert obj.name == frame_name
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
    (material,) = mesh.materials
    assert mesh.materials[face.material_index] == material
    shader = material.node_tree.nodes.get("Principled BSDF")
    assert tuple(shader.inputs["Base Color"].default_value) == (1.0, 0.0, 0.0, 1.0)


def test_import_duplicate_positions_preserves_uv_seam(scene):
    """重複座標を統合しつつ、共有頂点の面ごとの UV が残ることを確認する。

    Check that welding coincident vertices preserves UVs on each face corner.
    """
    assert import_text("uv_seam.x") == {"FINISHED"}

    (obj,) = scene.objects
    mesh = obj.data
    assert len(mesh.vertices) == 4
    assert len(mesh.polygons) == 2
    shared_vertex = next(v.index for v in mesh.vertices if tuple(v.co) == (1, 0, 0))
    uvs = mesh.uv_layers.active.uv
    assert {
        tuple(uvs[loop.index].vector)
        for loop in mesh.loops
        if loop.vertex_index == shared_vertex
    } == {(0.5, 1.0), (0.75, 1.0)}


def test_import_multiple_materials(scene):
    """面の順序と異なるマテリアル番号を読み込み、面と色の対応を確認する。

    Verify that face colors follow material indices even when their orders differ.
    """
    assert import_text("multiple_materials.x") == {"FINISHED"}
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="The text importer uses declaration order for named material references",
)
def test_import_named_material_reference(scene):
    """名前で参照したマテリアルが面に割り当てられることを確認する。

    現行実装は参照名に関係なく、先に宣言された青いマテリアルを割り当てる。

    Check that the face receives the named material selected by the reference.
    The current importer assigns the first declared material, which is blue.
    """
    assert import_text("material_reference.x") == {"FINISHED"}

    (obj,) = scene.objects
    (face,) = obj.data.polygons
    material = obj.data.materials[face.material_index]
    assert material.name == "ReferencedRed"
    shader = material.node_tree.nodes.get("Principled BSDF")
    assert tuple(shader.inputs["Base Color"].default_value) == (1.0, 0.0, 0.0, 1.0)


def test_import_empty_mesh(scene):
    """頂点も面もないメッシュを読み込み、オブジェクトが作られないことを確認する。

    Check that a mesh with zero vertices and faces creates no objects.
    """
    assert import_text("empty_mesh.x") == {"FINISHED"}
    assert len(scene.objects) == 0


def test_import_invalid_header(scene):
    """不正なヘッダーを拒否し、オブジェクトを作らないことを確認する。

    Reject an invalid header without creating objects.
    """
    with pytest.raises(RuntimeError, match="This file is not X file"):
        import_text("invalid_header.x")
    assert len(scene.objects) == 0
