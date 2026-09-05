bl_info = {
    "name": "Glamdring",
    "author": "Custom",
    "version": (1, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Shift + A > Light | Shift + Alt + L",
    "description": "1. Adjust Light strength similarly to grab, rotate and scale with 'Alt + shift + L' 2. Add Lamps tracked to empties",
    "category": "3D View",
}

import bpy
import math
from bpy.props import IntProperty
from bpy.app.handlers import persistent

# Global cache to keep track of light-to-target relationships across updates
_tracked_lights_cache = {}


# =========================================================================
# 1. INTERACTIVE MODAL POWER ADJUSTMENT UTILITIES
# =========================================================================

class MOUSE_OT_light_power_modal(bpy.types.Operator):
    bl_idname = "object.light_power_modal"
    bl_label = "Interactive Light Power"
    bl_options = {'REGISTER', 'UNDO'}

    first_mouse_x: IntProperty()

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'LIGHT' for obj in context.selected_objects)

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            delta = event.mouse_x - self.first_mouse_x
            sensitivity = 0.5 
            
            for obj, first_energy in self.lights_data.items():
                new_energy = first_energy + (delta * sensitivity)
                obj.data.energy = max(0.0, new_energy)
            
            if context.active_object and context.active_object.type == 'LIGHT':
                context.area.header_text_set(f"Active Light Power: {context.active_object.data.energy:.2f} W")
            else:
                context.area.header_text_set("Adjusting Selected Lights Power")

        elif event.type == 'LEFTMOUSE':
            context.area.header_text_set(None)
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            for obj, first_energy in self.lights_data.items():
                obj.data.energy = first_energy
            context.area.header_text_set(None)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        self.first_mouse_x = event.mouse_x
        self.lights_data = {
            obj: obj.data.energy 
            for obj in context.selected_objects 
            if obj.type == 'LIGHT'
        }
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


# =========================================================================
# 2. TRACKED LIGHT CREATION OPERATORS
# =========================================================================

class OBJECT_OT_add_tracked_light_base(bpy.types.Operator):
    bl_options = {'REGISTER', 'UNDO'}
    
    light_type: str = 'AREA' 
    light_name: str = "Tracked Area Light"

    def execute(self, context):
        # 1. Create the target Empty object exactly at World Origin (0,0,0)
        bpy.ops.object.empty_add(type='SPHERE', radius=0.25, location=(0.0, 0.0, 0.0))
        empty_obj = context.active_object
        empty_obj.name = f"{self.light_name}_Target"
        empty_obj.show_in_front = True

        # 2. Get the 3D Cursor location to spawn the chosen Light type
        light_spawn_loc = context.scene.cursor.location
        
        # 3. Instantiate the light data block
        light_data = bpy.data.lights.new(name=self.light_name, type=self.light_type)
        
        # Configure baseline properties based on the chosen type
        if self.light_type == 'AREA':
            light_data.size = 1.0  
        elif self.light_type == 'POINT':
            light_data.shadow_soft_size = 0.25  
        elif self.light_type == 'SUN':
            light_data.angle = 0.08  
        elif self.light_type == 'SPOT':
            light_data.spot_size = math.radians(45.0)  
            light_data.spot_blend = 0.5               

        # Create and link the physical light container object to the scene
        light_obj = bpy.data.objects.new(name=self.light_name, object_data=light_data)
        context.collection.objects.link(light_obj)
        light_obj.location = light_spawn_loc

        # 4. Add the 'Track To' Constraint pointing down at the Empty target
        constraint = light_obj.constraints.new(type='TRACK_TO')
        constraint.target = empty_obj
        constraint.track_axis = 'TRACK_NEGATIVE_Z'  
        constraint.up_axis = 'UP_Y'

        # Use Custom Pointer/String properties to link them in data
        light_obj["tracked_target_empty"] = empty_obj

        # 5. UI Cleanup: Focus viewport selection straight onto the new Light object
        bpy.ops.object.select_all(action='DESELECT')
        light_obj.select_set(True)
        context.view_layer.objects.active = light_obj

        return {'FINISHED'}


class OBJECT_OT_add_tracked_area(OBJECT_OT_add_tracked_light_base):
    bl_idname = "object.add_tracked_area_light"
    bl_label = "Tracked Area Light"
    bl_description = "New Tracked Area Light"
    light_type = 'AREA'
    light_name = "Tracked_Area_Light"

class OBJECT_OT_add_tracked_sun(OBJECT_OT_add_tracked_light_base):
    bl_idname = "object.add_tracked_sun_light"
    bl_label = "Tracked Sun Light"
    bl_description = "New Tracked Sun Light"
    light_type = 'SUN'
    light_name = "Tracked_Sun_Light"

class OBJECT_OT_add_tracked_point(OBJECT_OT_add_tracked_light_base):
    bl_idname = "object.add_tracked_point_light"
    bl_label = "Tracked Point Light"
    bl_description = "New Tracked Point Light"
    light_type = 'POINT'
    light_name = "Tracked_Point_Light"

class OBJECT_OT_add_tracked_spot(OBJECT_OT_add_tracked_light_base):
    bl_idname = "object.add_tracked_spot_light"
    bl_label = "Tracked Spot Light"
    bl_description = "New Tracked Spot Light"
    light_type = 'SPOT'
    light_name = "Tracked_Spot_Light"


# =========================================================================
# 3. BACKGROUND CLEANUP DELETION HANDLER
# =========================================================================

@persistent
def clean_orphaned_light_targets(scene):
    """Monitors the scene graph to auto-remove target Empties when their master light is deleted."""
    global _tracked_lights_cache
    
    current_tracked_lights = {
        obj for obj in bpy.data.objects 
        if obj.type == 'LIGHT' and "tracked_target_empty" in obj
    }
    
    for cached_light_ref, empty_obj in list(_tracked_lights_cache.items()):
        if cached_light_ref not in current_tracked_lights:
            try:
                if empty_obj and empty_obj.name in bpy.data.objects:
                    bpy.data.objects.remove(empty_obj, do_unlink=True)
            except ReferenceError:
                pass 
            
            _tracked_lights_cache.pop(cached_light_ref, None)

    for light in current_tracked_lights:
        target_empty = light["tracked_target_empty"]
        if target_empty:
            _tracked_lights_cache[light] = target_empty


# =========================================================================
# 4. REGISTRATION AND SETUP INTERFACES
# =========================================================================

# Registry array keeping track of all functional operator structures
classes = (
    MOUSE_OT_light_power_modal,
    OBJECT_OT_add_tracked_area,
    OBJECT_OT_add_tracked_sun,
    OBJECT_OT_add_tracked_point,
    OBJECT_OT_add_tracked_spot,
)

# Global list to store references to custom keymaps for safe deletion on unregister
addon_keymaps = []

def menu_func(self, context):
    self.layout.separator()
    self.layout.operator(OBJECT_OT_add_tracked_area.bl_idname, icon='LIGHT_AREA')
    self.layout.operator(OBJECT_OT_add_tracked_sun.bl_idname, icon='LIGHT_SUN')
    self.layout.operator(OBJECT_OT_add_tracked_point.bl_idname, icon='LIGHT_POINT')
    self.layout.operator(OBJECT_OT_add_tracked_spot.bl_idname, icon='LIGHT_SPOT')

def register():
    # 1. Register all core operator classes
    for cls in classes:
        bpy.utils.register_class(cls)
        
    # 2. Append submenus to Shift+A dropdown layout
    bpy.types.VIEW3D_MT_light_add.append(menu_func)
    
    # 3. Append the background deletion cleanup routines
    bpy.app.handlers.depsgraph_update_post.append(clean_orphaned_light_targets)

    # 4. Bind dynamic hotkey assignments (Alt + Shift + L)
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
        kmi = km.keymap_items.new(
            MOUSE_OT_light_power_modal.bl_idname, 
            type='L', 
            value='PRESS', 
            shift=True, 
            alt=True
        )
        addon_keymaps.append((km, kmi))

def unregister():
    # 1. Safely remove active hotkey layer references
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    
    # 2. Unlink core background scene update handlers
    bpy.app.handlers.depsgraph_update_post.remove(clean_orphaned_light_targets)
    
    # 3. Sever dropdown menu injections
    bpy.types.VIEW3D_MT_light_add.remove(menu_func)
    
    # 4. Unregister operator classes from internal system registry
    for cls in classes:
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
