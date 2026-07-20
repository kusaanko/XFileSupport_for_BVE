import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty, FloatVectorProperty
from bpy_extras.io_utils import ExportHelper
from .model_data_utility import ModelDataUtility
from .utility import float_to_str, vertex_to_str


# CSVファイルに出力 / Export to CSV file
class ExportCSVFile(bpy.types.Operator, ExportHelper):
    bl_idname = "export.csv_for_bve"
    bl_description = "Export to BVE CSV file (.csv)"
    bl_label = "Export BVE CSV File"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_options = {"UNDO"}

    filepath: StringProperty(name="export file", subtype="FILE_PATH")

    filename_ext = ".csv"

    filter_glob: StringProperty(
        default="*.csv",
        options={"HIDDEN"},
    )

    scale: FloatProperty(
        name="Scale",
        default=1.0,
    )

    export_selected_only: BoolProperty(
        name="Export only selected objects",
        default=False,
    )

    gamma_correction: BoolProperty(
        name="Gamma correction",
        default=True,
    )

    decal_transparent_color: FloatVectorProperty(
        name="Decal transparent color",
        size=4,
        subtype="COLOR",
        default=(0.0, 0.0, 0.0, 1.0),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def execute(self, context):
        if not self.filepath.endswith(".csv"):
            return {"CANCELLED"}

        model_data_utility = ModelDataUtility()
        model_data_utility.execute(
            context,
            export_selected_only=self.export_selected_only,
            scale=self.scale,
            gamma_correction=self.gamma_correction,
        )
        vertexes = model_data_utility.vertexes
        faces = model_data_utility.faces
        x_materials = model_data_utility.x_materials
        faces_use_material = model_data_utility.faces_use_material
        uv_data = model_data_utility.uv_data

        csv_file_content = ""

        # マテリアルごとに作成 / Create for each material
        for material_index in range(len(x_materials)):
            csv_file_content += "CreateMeshBuilder,\n"
            vertices_dict = {}
            vertices_list = []
            uv_vertices_list = []
            faces_no_duplicates = []
            x_material = x_materials[material_index]
            for face_index in range(len(faces)):
                x_material_index = faces_use_material[face_index]
                if x_material_index != material_index:
                    continue
                vertex_indices = []
                face = faces[face_index]
                for vertex_index in face:
                    vertex = vertexes[vertex_index]
                    # 頂点が他のデータと重複していたらそれを使用する / Use it if the vertex overlaps with other data
                    # 頂点とUVはセットなのでセットで重複を調べる / Vertices and UVs are sets, so check for duplicates in sets
                    uv = uv_data[vertex_index]
                    if x_material.texture_path == "":
                        uv = (0.0, 0.0)
                    key = vertex_to_str(vertex) + str(uv)
                    if key not in vertices_dict.keys():
                        vertices_dict[key] = len(vertices_dict.keys())
                        vertices_list.append(vertex)
                        uv_vertices_list.append(uv)
                    vertex_indices.append(vertices_dict[key])
                faces_no_duplicates.append(vertex_indices)
            # 頂点データ / Vertex data
            for vertex in vertices_list:
                csv_file_content += (
                    "AddVertex,"
                    + float_to_str(vertex[0])
                    + ","
                    + float_to_str(vertex[2])
                    + ","
                    + float_to_str(vertex[1])
                    + "\n"
                )
            # 面データ / Face data
            for face in faces_no_duplicates:
                csv_file_content += "AddFace,"
                for vertex_index in face:
                    csv_file_content += str(vertex_index) + ","
                csv_file_content = csv_file_content[0:-1] + "\n"
            csv_file_content += "GenerateNormals\n"
            has_texture = False
            if x_material.texture_path != "":
                csv_file_content += "LoadTexture," + x_material.texture_path + "\n"
                csv_file_content += (
                    "SetDecalTransparentColor,"
                    + str(round(self.decal_transparent_color[0] * 255))
                    + ","
                    + str(round(self.decal_transparent_color[1] * 255))
                    + ","
                    + str(round(self.decal_transparent_color[2] * 255))
                    + ","
                    + str(round(self.decal_transparent_color[3] * 255))
                    + "\n"
                )
                has_texture = True
            # 面色 / Face color
            csv_file_content += (
                "SetColor,"
                + str(round(x_material.face_color[0] * 255))
                + ","
                + str(round(x_material.face_color[1] * 255))
                + ","
                + str(round(x_material.face_color[2] * 255))
                + ","
                + str(round(x_material.face_color[3] * 255))
                + "\n"
            )
            # UVデータ / UV data
            if has_texture:
                for i in range(0, len(uv_vertices_list)):
                    csv_file_content += (
                        "SetTextureCoordinates,"
                        + str(i)
                        + ","
                        + float_to_str(uv_vertices_list[i][0])
                        + ","
                        + float_to_str(-uv_vertices_list[i][1] + 1)
                        + "\n"
                    )

        with open(self.filepath, mode="w") as f:
            f.write(csv_file_content)
        return {"FINISHED"}
