import bpy, math, json, os, sys
from mathutils import Vector

SRC=os.environ.get('HOGWARTS_GLB','external/Story-map/public/3D-Model/Hogwarts.glb')
OUT=os.environ.get('HOGWARTS_OUT','hogwarts_external/output')
os.makedirs(OUT,exist_ok=True)

# Clear default scene.
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

print('IMPORT', SRC)
bpy.ops.import_scene.gltf(filepath=SRC)

# Keep only imported mesh objects for bounds; remove imported cameras/lights to control inspection lighting.
for o in list(bpy.context.scene.objects):
    if o.type in {'CAMERA','LIGHT'}:
        bpy.data.objects.remove(o, do_unlink=True)
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
if not meshes:
    raise RuntimeError('No mesh objects found in GLB')

# World-space bounds.
pts=[]
for o in meshes:
    for c in o.bound_box:
        pts.append(o.matrix_world @ Vector(c))
mins=Vector((min(p.x for p in pts),min(p.y for p in pts),min(p.z for p in pts)))
maxs=Vector((max(p.x for p in pts),max(p.y for p in pts),max(p.z for p in pts)))
center=(mins+maxs)/2
dims=maxs-mins
maxdim=max(dims)

# Geometry stats.
triangles=0
vertices=0
materials=set()
for o in meshes:
    vertices += len(o.data.vertices)
    for p in o.data.polygons:
        triangles += max(1,len(p.vertices)-2)
    for slot in o.material_slots:
        if slot.material: materials.add(slot.material.name)
stats={
    'source':SRC,
    'mesh_objects':len(meshes),
    'vertices':vertices,
    'triangles_estimate':triangles,
    'materials':len(materials),
    'bounds_min':list(mins),
    'bounds_max':list(maxs),
    'dimensions':list(dims),
    'center':list(center),
}
with open(os.path.join(OUT,'stats.json'),'w') as f: json.dump(stats,f,indent=2)
print(json.dumps(stats,indent=2))

scene=bpy.context.scene
# Blender 4.2+ renamed Eevee to BLENDER_EEVEE_NEXT.
try:
    scene.render.engine='BLENDER_EEVEE_NEXT'
except Exception:
    scene.render.engine='BLENDER_WORKBENCH'
scene.render.resolution_x=1280
scene.render.resolution_y=720
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.render.film_transparent=False
scene.world.color=(0.055,0.065,0.08)

# Neutral inspection floor, placed just under model.
bpy.ops.mesh.primitive_plane_add(size=maxdim*6,location=(center.x,center.y,mins.z-maxdim*.012))
floor=bpy.context.object
floor.name='InspectionFloor'
mat=bpy.data.materials.new('InspectionFloorMat')
mat.diffuse_color=(0.11,0.12,0.14,1)
mat.use_nodes=True
bsdf=mat.node_tree.nodes.get('Principled BSDF')
if bsdf:
    bsdf.inputs['Base Color'].default_value=(0.11,0.12,0.14,1)
    bsdf.inputs['Roughness'].default_value=.95
floor.data.materials.append(mat)

# Studio lighting.
bpy.ops.object.light_add(type='SUN', location=(center.x-maxdim,center.y-maxdim,center.z+maxdim*2))
sun=bpy.context.object; sun.data.energy=2.2
sun.rotation_euler=(math.radians(32),math.radians(-18),math.radians(-38))
bpy.ops.object.light_add(type='AREA', location=(center.x-maxdim*.8,center.y-maxdim*.9,center.z+maxdim*1.4))
key=bpy.context.object; key.data.energy=1800; key.data.shape='DISK'; key.data.size=maxdim*1.5
bpy.ops.object.light_add(type='AREA', location=(center.x+maxdim*.8,center.y+maxdim*.5,center.z+maxdim*.7))
fill=bpy.context.object; fill.data.energy=900; fill.data.shape='DISK'; fill.data.size=maxdim*1.2

def point_at(obj,target):
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
point_at(key,center); point_at(fill,center)

# Ortho camera renderer. Views are axis-relative because source orientation may be unknown.
def render_view(name,dirv):
    d=Vector(dirv).normalized()
    loc=center+d*maxdim*2.6
    if abs(d.z)<0.2:
        loc.z += dims.z*.08
    bpy.ops.object.camera_add(location=loc)
    cam=bpy.context.object; cam.name='CAM_'+name
    cam.data.type='ORTHO'
    horizontal=math.sqrt(dims.x*dims.x+dims.y*dims.y)
    cam.data.ortho_scale=max(dims.z*1.45,horizontal*.72)*1.08
    point_at(cam,center+Vector((0,0,dims.z*.05)))
    scene.camera=cam
    scene.render.filepath=os.path.join(OUT,name+'.png')
    bpy.ops.render.render(write_still=True)
    if not os.path.exists(scene.render.filepath):
        raise RuntimeError('Render missing: '+scene.render.filepath)
    bpy.data.objects.remove(cam,do_unlink=True)

views={
 'y_minus_front':(0,-1,.08),
 'x_minus_left':(-1,0,.08),
 'x_plus_right':(1,0,.08),
 'y_plus_rear':(0,1,.08),
 'diag_xm_ym':(-1,-1,.18),
 'diag_xp_ym':(1,-1,.18),
 'diag_xm_yp':(-1,1,.18),
 'diag_xp_yp':(1,1,.18),
 'top':(0,0,1),
}
for name,d in views.items():
    render_view(name,d)

print('DONE',OUT)
