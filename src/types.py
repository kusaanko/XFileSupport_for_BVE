import bpy
from bpy.props import (
    StringProperty,
    BoolProperty,
    FloatVectorProperty,
    EnumProperty,
    IntProperty,
)


# Custom node type
class CustomOpenBveCsvNode(bpy.types.Node):
    bl_idname = "OpenBveCsv"  # Unique identifier for the node
    bl_label = (
        "OpenBVE CSV Properties"  # Name that will appear on the node in the editor
    )

    use_add_face_2: BoolProperty(
        name="Use AddFace2",
        default=False,
    )

    enable_cross_fading: BoolProperty(
        name="Enable cross-fading",
        default=False,
    )

    use_blend_mode: BoolProperty(
        name="Use blend mode",
        default=False,
    )

    blend_mode: EnumProperty(
        name="Blend mode",
        items=[
            ("Normal", "Normal", "The faces are rendered normally."),
            ("Additive", "Additive", "The faces are rendered additively."),
        ],
        default="Normal",
    )

    glow_half_distance: IntProperty(
        name="Glow half distance",
        default=0,
        max=4095,
        min=0,
    )

    glow_attenuation_mode: EnumProperty(
        name="Glow attenuation mode",
        items=[
            (
                "DivideExponent2",
                "DivideExponent2",
                "The glow intensity is determined via the function x2 / (x2 + GlowHalfDistance2), where x is the distance from the camera to the object in meters.",
            ),
            (
                "DivideExponent4",
                "DivideExponent4",
                "The glow intensity is determined via the function x4 / (x4 + GlowHalfDistance4), where x is the distance from the camera to the object in meters.",
            ),
        ],
        default="DivideExponent4",
    )

    use_decal_transparent_color: BoolProperty(
        name="Use decal transparent color",
        default=False,
    )

    decal_transparent_color: FloatVectorProperty(
        name="Decal transparent color",
        size=4,
        subtype="COLOR",
        default=(0.0, 0.0, 0.0, 1.0),
    )

    nighttime_texture_path: StringProperty(
        name="Nighttime texture",
        default="",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # Additional buttons displayed on the node.
    def draw_buttons(self, context, layout):
        layout.prop(self, "use_add_face_2")
        layout.prop(self, "enable_cross_fading")
        layout.prop(self, "use_blend_mode")
        layout.prop(self, "blend_mode")
        layout.prop(self, "glow_half_distance")
        layout.prop(self, "glow_attenuation_mode")
        layout.prop(self, "nighttime_texture_path")
        layout.prop(self, "use_decal_transparent_color")
        layout.prop(self, "decal_transparent_color")

    def update(self):
        pass
