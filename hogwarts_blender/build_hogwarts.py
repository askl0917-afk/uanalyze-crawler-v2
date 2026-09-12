import bpy, math, os
from mathutils import Vector
from math import sin, cos, pi

OUT=os.path.join(os.path.dirname(__file__),'output')
os.makedirs(OUT,exist_ok=True)

# ---------- scene ----------
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for datablocks in (bpy.data.meshes,bpy.data.curves,bpy.data.materials,bpy.data.cameras,bpy.data.lights):
    pass
scene=bpy.context.scene
scene.render.engine='BLENDER_EEVEE'
try:
    scene.eevee.use_gtao=True
    scene.eevee.gtao_distance=6
    scene.eevee.gtao_factor=1.35
except: pass
scene.render.resolution_x=1280
scene.render.resolution_y=720
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.world.color=(0.035,0.045,0.065)

# ---------- materials ----------
def mat(name,color,rough=.7,metal=0.0,alpha=1.0):
    m=bpy.data.materials.new(name)
    m.diffuse_color=(*color,alpha)
    m.use_nodes=True
    bs=m.node_tree.nodes.get('Principled BSDF')
    bs.inputs['Base Color'].default_value=(*color,1)
    bs.inputs['Roughness'].default_value=rough
    bs.inputs['Metallic'].default_value=metal
    if alpha<1:
        bs.inputs['Alpha'].default_value=alpha
        m.blend_method='BLEND'
        m.show_transparent_back=True
    return m
STONE=mat('Stone',(0.31,0.32,0.31),.95)
STONE2=mat('StoneDark',(0.19,0.20,0.19),1)
ROOF=mat('Slate',(0.055,0.075,0.085),.85)
WINDOW=mat('Window',(0.045,0.08,0.10),.25)
GLASS=mat('GreenhouseGlass',(0.22,0.42,0.39),.18,alpha=.48)
GROUND=mat('Ground',(0.14,0.18,0.12),1)
CLIFF=mat('Cliff',(0.22,0.23,0.21),1)
WATER=mat('Water',(0.03,0.08,0.10),.18,alpha=.72)
WOOD=mat('Wood',(0.18,0.11,0.07),.85)

# ---------- helpers ----------
def finish(obj,material=None,bevel=.0):
    if material: obj.data.materials.append(material)
    if bevel>0:
        b=obj.modifiers.new('Bevel','BEVEL'); b.width=bevel; b.segments=2
    return obj

def box(name,loc,size,material=STONE,rot=0,bevel=.12):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=(0,0,rot))
    o=bpy.context.object; o.name=name; o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    return finish(o,material,bevel)

def cyl(name,loc,radius,depth,material=STONE,verts=16,bevel=.08):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts,radius=radius,depth=depth,location=loc)
    o=bpy.context.object; o.name=name
    return finish(o,material,bevel)

def cone(name,loc,r1,r2,depth,material=ROOF,verts=16):
    bpy.ops.mesh.primitive_cone_add(vertices=verts,radius1=r1,radius2=r2,depth=depth,location=loc)
    o=bpy.context.object; o.name=name
    return finish(o,material,.05)

def gable(name,loc,length,width,height,rot=0,material=ROOF):
    L=length/2; W=width/2; H=height
    verts=[(-L,-W,0),(L,-W,0),(-L,W,0),(L,W,0),(-L,0,H),(L,0,H)]
    faces=[(0,1,5,4),(2,4,5,3),(0,2,3,1),(0,4,2),(1,3,5)]
    mesh=bpy.data.meshes.new(name+'Mesh'); mesh.from_pydata(verts,[],faces); mesh.update()
    o=bpy.data.objects.new(name,mesh); bpy.context.collection.objects.link(o)
    o.location=loc; o.rotation_euler[2]=rot
    return finish(o,material,.08)

def beam_between(name,a,b,r=.35,material=STONE):
    a,b=Vector(a),Vector(b); d=b-a; L=d.length
    mid=(a+b)/2
    bpy.ops.mesh.primitive_cylinder_add(vertices=10,radius=r,depth=L,location=mid)
    o=bpy.context.object; o.name=name
    o.rotation_mode='QUATERNION'; o.rotation_quaternion=d.to_track_quat('Z','Y')
    return finish(o,material,.02)

def gothic_window(name,loc,scale=(1.1,.18,3.2),rot=0):
    return box(name,loc,scale,WINDOW,rot,.03)

def tower_round(name,x,y,base_z,r,h,roof_h,verts=16):
    cyl(name,(x,y,base_z+h/2),r,h,STONE,verts,.14)
    # crown band
    cyl(name+'_crown',(x,y,base_z+h-.8),r*1.06,1.2,STONE2,verts,.08)
    cone(name+'_roof',(x,y,base_z+h+roof_h/2-.1),r*1.12,.18,roof_h,ROOF,verts)
    # windows in 3 tiers
    for zi in (base_z+h*.35,base_z+h*.55,base_z+h*.75):
        for k in range(0,verts,2):
            a=2*pi*k/verts
            px=x+cos(a)*(r+.035); py=y+sin(a)*(r+.035)
            o=gothic_window(name+'_w',(px,py,zi),(.85,.14,2.4),a+pi/2)
    return

def tower_square(name,x,y,base_z,w,d,h,roof_h,rot=0):
    box(name,(x,y,base_z+h/2),(w,d,h),STONE,rot,.15)
    gable(name+'_roof',(x,y,base_z+h),w*1.12,d*1.12,roof_h,rot,ROOF)
    for zi in (base_z+h*.45,base_z+h*.68):
        for s in (-1,1):
            # front/back windows
            off=d/2+.05
            gothic_window(name+'_wf',(x+s*w*.22,y-off,zi),(1.0,.14,2.8),rot)
            gothic_window(name+'_wb',(x+s*w*.22,y+off,zi),(1.0,.14,2.8),rot)

def add_buttresses_along_hall(cx,cy,L,W,z0,h,rot=0):
    for x in [(-L/2)+3+i*5 for i in range(max(1,int((L-6)/5)+1))]:
        # local->world
        for side in (-1,1):
            lx=x; ly=side*(W/2+1.0)
            wx=cx+lx*cos(rot)-ly*sin(rot); wy=cy+lx*sin(rot)+ly*cos(rot)
            box('Buttress',(wx,wy,z0+h*.34),(.85,2.0,h*.68),STONE2,rot,.05)

def hall(name,cx,cy,z0,L,W,H,roof_h,rot=0,window_count=7):
    box(name,(cx,cy,z0+H/2),(L,W,H),STONE,rot,.18)
    gable(name+'_roof',(cx,cy,z0+H),L*1.04,W*1.12,roof_h,rot,ROOF)
    add_buttresses_along_hall(cx,cy,L,W,z0,H,rot)
    for i in range(window_count):
        lx=-L*.38+i*(L*.76/max(1,window_count-1))
        for side in (-1,1):
            ly=side*(W/2+.06)
            wx=cx+lx*cos(rot)-ly*sin(rot); wy=cy+lx*sin(rot)+ly*cos(rot)
            gothic_window(name+'_win',(wx,wy,z0+H*.57),(1.25,.14,4.1),rot)

# ---------- terrain ----------
N=46; step=3.5; verts=[]; faces=[]
for j in range(N):
    y=(j-(N-1)/2)*step
    for i in range(N):
        x=(i-(N-1)/2)*step
        # plateau concentrated near castle; strong cliff to lake side (negative y)
        r=math.sqrt((x*0.72)**2+(y*0.9)**2)
        plateau=15.5*math.exp(-(r/52)**4)
        ridge=6.0*math.exp(-(((x-7)/36)**2+((y-7)/28)**2))
        lake_cut=-5.5/(1+math.exp((y+28)/4))
        ripple=1.1*sin(x*.12)*cos(y*.10)+.55*sin((x+y)*.18)
        z=max(-6, plateau+ridge+lake_cut+ripple)
        verts.append((x,y,z))
for j in range(N-1):
    for i in range(N-1):
        a=j*N+i; faces.append((a,a+1,a+1+N,a+N))
me=bpy.data.meshes.new('TerrainMesh'); me.from_pydata(verts,[],faces); me.update()
terrain=bpy.data.objects.new('Terrain',me); bpy.context.collection.objects.link(terrain); finish(terrain,GROUND,.0)
# cliff skirting and lake
box('CliffCore',(0,-2,3),(104,88,18),CLIFF,0,.8)
box('Lake',(0,-72,-5.2),(220,120,.7),WATER,0,.02)

# ---------- castle massing: film-oriented hierarchy ----------
# Great Hall (west / lake-facing long axis)
hall('GreatHall',-23,-5,17,46,15,15,8,math.radians(-8),8)
# end chapel / lantern
cyl('GreatHallApse',(-45,1,24),7.2,14,STONE,18,.15); cone('GreatHallApseRoof',(-45,1,35),8.0,.3,9,ROOF,18)
# Grand Staircase / central tower
tower_round('GrandStaircaseTower',1,5,19,8.8,34,11,18)
# Astronomy Tower - dominant highest point
tower_round('AstronomyTower',22,9,18,8.5,46,13,18)
# secondary turret on Astronomy complex
tower_round('AstronomyTurret',30,7,19,4.4,27,8,14)
# Bell Towers pair east of central cluster
tower_square('BellTowerA',8,22,19,8,8,28,8,math.radians(4))
tower_square('BellTowerB',17,23,19,8,8,28,8,math.radians(4))
# Clock Tower and courtyard buildings
tower_square('ClockTower',-7,28,17,10,9,30,9,math.radians(-3))
hall('ClockWing',-13,20,17,25,10,13,6,math.radians(-4),4)
hall('EastWing',24,22,18,26,11,14,7,math.radians(10),5)
hall('NorthWing',1,32,17,28,10,13,6,math.radians(3),5)
# courtyard cloister blocks
hall('CourtyardWest',-3,14,17,20,7,10,4,math.radians(90),3)
hall('CourtyardEast',14,14,17,19,7,10,4,math.radians(90),3)
# small turrets / roof skyline
for idx,(x,y,r,h) in enumerate([(-11,5,3.6,20),(-3,-1,3.2,18),(31,18,3.5,21),(-19,24,3.1,18),(5,35,3.2,19),(35,9,3.0,18)]):
    tower_round('Turret%02d'%idx,x,y,19,r,h,6,12)

# ---------- Viaduct: deck + piers + arched ribs ----------
A=Vector((-35,-10,18)); B=Vector((-67,-35,8)); segments=7
v=B-A; L=v.length; ang=math.atan2(v.y,v.x); mid=(A+B)/2
box('ViaductDeck',(mid.x,mid.y,mid.z+1.1),(L,5.2,2.2),STONE2,ang,.15)
pts=[]
for i in range(segments+1):
    t=i/segments; p=A.lerp(B,t); ground_z=-1.5+3*(1-t)
    pts.append((p.x,p.y,ground_z,p.z))
    box('ViaductPier%02d'%i,(p.x,p.y,(ground_z+p.z)/2),(2.1,3.2,p.z-ground_z),STONE2,ang,.05)
for i in range(segments):
    p0=A.lerp(B,i/segments); p1=A.lerp(B,(i+1)/segments)
    chord=(p1-p0); side=Vector((-chord.y,chord.x,0)).normalized()
    # arch in vertical plane using segmented beams
    prev=None
    for k in range(11):
        t=k/10
        base=p0.lerp(p1,t); zbase=-.5+3*(1-((i+t)/segments))
        z= zbase + (p0.z-zbase)*(.15 + .85*math.sin(pi*t))
        q=Vector((base.x,base.y,z))
        if prev is not None: beam_between('Arch',prev,q,.42,STONE)
        prev=q

# ---------- Greenhouses ----------
for gi,x in enumerate((30,36,42)):
    box('GreenhouseBase%d'%gi,(x,-5,18.5),(5.5,18,1.0),STONE2,0,.05)
    box('GreenhouseGlass%d'%gi,(x,-5,21.5),(5.2,17.4,5.5),GLASS,0,.04)
    gable('GreenhouseRoof%d'%gi,(x,-5,24.25),5.4,17.8,3.0,math.radians(90),GLASS)

# ---------- Boathouse ----------
hall('Boathouse',-37,-45,3.0,16,9,7,4,math.radians(-25),3)
# cliff stair / terraces
for i in range(13):
    t=i/12
    x=-35+18*t; y=-41+30*t; z=6+10*t
    box('CliffStep%02d'%i,(x,y,z),(5.0,2.2,.8),STONE2,math.radians(31),.04)
# walls / terraces
box('SouthWall',(-3,-18,19),(48,2.4,6),STONE2,math.radians(-3),.08)
box('EastTerrace',(35,4,19),(2.8,37,7),STONE2,math.radians(4),.08)

# ---------- extra rooflets and pinnacles ----------
for i,(x,y,z) in enumerate([(-22,-12,33),(-9,-12,31),(-30,3,33),(10,17,49),(17,18,49),(23,14,71),(3,2,61),(-7,28,56)]):
    cone('Pinnacle%d'%i,(x,y,z),1.35,.05,6.2,ROOF,10)

# ---------- lighting ----------
bpy.ops.object.light_add(type='SUN',location=(0,0,80))
sun=bpy.context.object; sun.data.energy=2.0; sun.rotation_euler=(math.radians(28),math.radians(-18),math.radians(-35))
bpy.ops.object.light_add(type='AREA',location=(-35,-45,70))
area=bpy.context.object; area.data.energy=1200; area.data.size=55
area.rotation_euler=(math.radians(25),0,math.radians(-28))

# ---------- camera/render ----------
def track(cam,target):
    d=Vector(target)-cam.location
    cam.rotation_euler=d.to_track_quat('-Z','Y').to_euler()
def render_cam(name,loc,target=(0,4,26),lens=52):
    bpy.ops.object.camera_add(location=loc)
    cam=bpy.context.object; cam.name='CAM_'+name; cam.data.lens=lens; track(cam,target)
    scene.camera=cam; scene.render.filepath=os.path.join(OUT,name+'.png'); bpy.ops.render.render(write_still=True)
    return cam

cameras=[
 ('front_lake',(-90,-105,48),(0,3,27),58),
 ('front_left',(-105,-72,62),(0,5,28),55),
 ('front_right',(92,-70,61),(0,5,28),55),
 ('left',(-125,5,48),(0,8,27),60),
 ('right',(125,5,48),(0,8,27),60),
 ('rear',(5,126,55),(0,8,27),58),
 ('top',(0,5,155),(0,5,18),60),
 ('aerial',(-78,-76,105),(0,5,24),55)
]
for c in cameras: render_cam(*c)

# ---------- save/export ----------
scene.render.filepath=os.path.join(OUT,'front_left.png')
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'hogwarts_geometry_v1.blend'))
# remove cameras/lights from GLB selection? Export all meshes/materials, cameras excluded.
for o in bpy.context.scene.objects: o.select_set(o.type=='MESH')
bpy.context.view_layer.objects.active=next((o for o in scene.objects if o.type=='MESH'),None)
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT,'hogwarts_geometry_v1.glb'),export_format='GLB',use_selection=True,export_apply=True)
print('DONE',OUT)
