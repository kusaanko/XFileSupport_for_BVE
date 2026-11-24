import bpy
import pytest

import src


@pytest.fixture(scope="module")
def addon():
    src.register()
    yield
    src.unregister()


@pytest.fixture
def scene(addon):
    window = bpy.context.window
    original_scene = window.scene
    test_scene = bpy.data.scenes.new("Format tests")
    original_meshes = set(bpy.data.meshes)
    original_materials = set(bpy.data.materials)
    original_images = set(bpy.data.images)
    window.scene = test_scene
    try:
        yield test_scene
    finally:
        window.scene = original_scene
        for obj in list(test_scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(test_scene)
        for mesh in set(bpy.data.meshes) - original_meshes:
            bpy.data.meshes.remove(mesh)
        for material in set(bpy.data.materials) - original_materials:
            bpy.data.materials.remove(material)
        for image in set(bpy.data.images) - original_images:
            bpy.data.images.remove(image)
