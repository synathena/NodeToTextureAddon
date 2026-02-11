bl_info = {
    "name": "Material Nodes To Texture",
    "author": "Athina Syntychaki",
    "version": (1.0),
    "blender": (4, 0, 0),
    "location": "Node Editor > Sidebar > Node to Texture",
    "description": "Bakes active node's output to texture",
    "category": "Bake",
}

import bpy
import os

def get_unique_path(folder, filename, extension):
    base_name = filename
    counter = 1
    full_path = os.path.join(folder, f"{base_name}.{extension}")
    while os.path.exists(full_path):
        full_path = os.path.join(folder, f"{base_name}_{counter:03d}.{extension}")
        counter += 1
    return full_path

def get_default_path():
    if bpy.data.is_saved:
        return os.path.join(os.path.dirname(bpy.data.filepath), "Baked_Nodes")
    return os.path.join(os.path.expanduser("~"), "Blender_Baked_Nodes")

class NTT_OT_BakeNodes(bpy.types.Operator):
    bl_idname = "node.to_texture"
    bl_label = "Bake Selected to Texture"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        obj = context.active_object
        
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a Mesh object first.")
            return {'CANCELLED'}

        mat = obj.active_material
        if not mat or not mat.use_nodes:
            self.report({'ERROR'}, "Object has no material.")
            return {'CANCELLED'}

        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        active_node = nodes.active
        
        if not active_node:
            self.report({'ERROR'}, "No Active node found.")
            return {'CANCELLED'}

        output_socket = active_node.outputs[0]
        for sock in active_node.outputs:
            if sock.is_linked:
                output_socket = sock
                break
        
        original_destinations = [link.to_socket for link in output_socket.links]

        save_folder = sc.NTT_bake_path or get_default_path()
        if not os.path.exists(save_folder): os.makedirs(save_folder)

        ext = "exr" if sc.NTT_use_float else "png"
        base_filename = sc.NTT_bake_name.strip() or f"Baked_{active_node.name}"
        target_filepath = get_unique_path(save_folder, base_filename, ext)
        final_name = os.path.splitext(os.path.basename(target_filepath))[0]

        # Setup Target Image
        image = bpy.data.images.new(
            final_name, 
            width=sc.NTT_resolution, 
            height=sc.NTT_resolution, 
            float_buffer=sc.NTT_use_float,
            alpha=False 
        )
        image.colorspace_settings.name = 'Non-Color' if sc.NTT_bake_type in ['NORMAL', 'DATA'] else 'sRGB'

        target_tex_node = nodes.new('ShaderNodeTexImage')
        target_tex_node.image = image
        target_tex_node.location = (active_node.location.x + 400, active_node.location.y)

        #color management save
        r = context.scene.render
        orig_engine = r.engine
        cv = context.scene.view_settings
        orig_transform = cv.view_transform
        orig_exposure = cv.exposure
        orig_gamma = cv.gamma

        try:
            r.engine = 'CYCLES'
            cv.view_transform = 'Standard'
            cv.exposure = 0.0
            cv.gamma = 1.0
            
            nodes.active = target_tex_node 

            # setup Temporary Output Bridge
            temp_out = nodes.new('ShaderNodeOutputMaterial')
            temp_out.is_active_output = True
            
            if sc.NTT_bake_type == 'NORMAL':
                temp_bsdf = nodes.new('ShaderNodeBsdfPrincipled')
                links.new(output_socket, temp_bsdf.inputs['Normal'])
                links.new(temp_bsdf.outputs[0], temp_out.inputs['Surface'])
                
                r.bake.use_pass_direct = False
                r.bake.use_pass_indirect = False
                r.bake.use_pass_color = False
                r.bake.normal_space = 'TANGENT'
                bpy.ops.object.bake(type='NORMAL')
                nodes.remove(temp_bsdf)
            else:
                temp_emit = nodes.new('ShaderNodeEmission')
                links.new(output_socket, temp_emit.inputs['Color'])
                links.new(temp_emit.outputs[0], temp_out.inputs['Surface'])
                bpy.ops.object.bake(type='EMIT')
                nodes.remove(temp_emit)

            nodes.remove(temp_out)
            image.filepath_raw = target_filepath
            image.file_format = 'OPEN_EXR' if sc.NTT_use_float else 'PNG'
            image.save()
            
        except Exception as e:
            self.report({'ERROR'}, f"Bake failed: {e}")
        finally:
            r.engine = orig_engine
            cv.view_transform = orig_transform
            cv.exposure = orig_exposure
            cv.gamma = orig_gamma

        if sc.NTT_bake_type == 'NORMAL':
            norm_map_node = nodes.new('ShaderNodeNormalMap')
            norm_map_node.location = (target_tex_node.location.x + 250, target_tex_node.location.y)
            links.new(target_tex_node.outputs['Color'], norm_map_node.inputs['Color'])
            for target_socket in original_destinations:
                links.new(norm_map_node.outputs['Normal'], target_socket)
        else:
            for target_socket in original_destinations:
                links.new(target_tex_node.outputs['Color'], target_socket)

        self.report({'INFO'}, f"Baked: {final_name}")
        return {'FINISHED'}
