# https://github.com/kusaanko/Blender_XFileSupport_BVE
#
# Copyright (c) 2021 kusaanko
# This is licensed under GPL v3.0 or later
# see https://github.com/kusaanko/Blender_XFileSupport_BVE/blob/main/LICENSE

import bpy

from .export_csv_openbve import ExportOpenBveCSVFile
from .types import CustomOpenBveCsvNode
from .export_csv import ExportCSVFile
from .direct_x import ExportDirectXXFile, ImportDirectXXFile

# locale
#    (target_context, key): translated_str
translations_dict = {
    "ja_JP": {
        (
            "*",
            "Remove All Objects and Materials",
        ): "全てのオブジェクトとマテリアルを削除する",
        ("*", "Gamma correction"): "ガンマ補正",
        ("*", "This file is not X file!"): "このファイルはXファイルではありません！",
        ("*", "Output mode"): "出力モード",
        ("*", "Binary"): "バイナリ",
        ("*", "Text mode"): "テキストモード",
        ("*", "Binary mode"): "バイナリモード",
        ("*", "Binary + Compress"): "バイナリ+圧縮",
        ("*", "Compressed binary mode"): "圧縮したバイナリモード",
        ("*", "Export material name"): "マテリアル名を出力する",
        ("*", "Export onyl selected objects"): "選択したオブジェクトのみエクスポート",
        ("*", "Export only necessary data"): "必要なデータのみエクスポート",
        ("*", "Gamma correction is not 2.2"): "ガンマ補正は2.2である必要があります",
        (
            "*",
            "This plug-in is for Bve. So some features are not supported.",
        ): "このプラグインはBve向けです。そのため、一部の機能はサポートされていません。",
        ("*", "For OpenBVE"): "OpenBVE向け",
        ("*", "Use decal transparent color"): "透過色を使用する",
        ("*", "Decal transparent color"): "テクスチャの透過色",
        ("*", "Enable cross-fading"): "cross-fadingを有効にする",
        ("*", "Use blend mode"): "ブレンドモードを使用する",
        ("*", "Nighttime texture"): "夜間テクスチャ",
        ("*", "Glow attenuation mode"): "Glow減衰モード",
        ("*", "OpenBVE CSV Properties"): "OpenBVE CSVプロパティ",
        (
            "*",
            "Use texture name instead of texture path",
        ): "テクスチャのパスの代わりにテクスチャ名を使用する",
        (
            "*",
            "This is useful when you want to use a relative path",
        ): "相対パスを使用したい場合に便利です",
        ("*", "Use AddFace2"): "AddFace2を使用する",
        ("*", "Use AddFace2 instead of AddFace"): "AddFaceの代わりにAddFace2を使用する",
        ("*", "Use emissive power"): "放射強度を使用する",
        (
            "*",
            "Multiply emissive color by emissive power",
        ): "放射色に放射強度を掛けます",
    }
}


# メニューに追加 / Add to the menu
def menu_func_import(self, context):
    self.layout.operator(
        ImportDirectXXFile.bl_idname, text="DirectX XFile (.x) for BVE"
    )


def menu_func_export(self, context):
    self.layout.operator(
        ExportDirectXXFile.bl_idname, text="DirectX XFile (.x) for BVE"
    )
    self.layout.operator(ExportCSVFile.bl_idname, text="CSV (.csv) for BVE")
    self.layout.operator(ExportOpenBveCSVFile.bl_idname, text="CSV (.csv) for OpenBVE")


def add_node_to_menu(self, context):
    layout = self.layout
    props = layout.operator("node.add_node", text="OpenBVE CSV Properties")
    props.type = CustomOpenBveCsvNode.bl_idname
    return props


classes = (
    ImportDirectXXFile,
    ExportDirectXXFile,
    ExportCSVFile,
    ExportOpenBveCSVFile,
    CustomOpenBveCsvNode,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

    bpy.types.NODE_MT_add.append(add_node_to_menu)

    bpy.app.translations.register(__name__, translations_dict)


def unregister():
    bpy.app.translations.unregister(__name__)

    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.NODE_MT_add.remove(add_node_to_menu)

    for cls in classes:
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
