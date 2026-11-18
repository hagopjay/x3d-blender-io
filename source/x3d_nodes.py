# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Element names an exported X3D file may contain.

Generated from the concrete node classes of x3d.py 4.0.65.8 (which includes the 4.1 ``GaussianSplats``) plus the
structural elements (X3D, head, meta, component, unit, Scene, ROUTE, IS, connect, field, fieldValue, proto and
IMPORT/EXPORT statements) and the H3D ``TransformInfo`` the add-on writes under ``use_h3d``. The validator uses it so
that an invented element such as ``<Banana>`` is an error instead of passing as "well-formed XML". It is a name list,
not the schema: attributes and nesting are checked by the XSD and x3d.py when they are available.
"""

KNOWN_ELEMENTS = frozenset((
    "AcousticProperties", "Analyser", "Anchor", "Appearance", "Arc2D", "ArcClose2D", "AudioClip", "AudioDestination",
    "Background", "BallJoint", "Billboard", "BiquadFilter", "BlendedVolumeStyle", "BooleanFilter", "BooleanSequencer",
    "BooleanToggle", "BooleanTrigger", "BoundaryEnhancementVolumeStyle", "BoundedPhysicsModel", "Box",
    "BufferAudioSource", "CADAssembly", "CADFace", "CADLayer", "CADPart", "CartoonVolumeStyle", "ChannelMerger",
    "ChannelSelector", "ChannelSplitter", "Circle2D", "ClipPlane", "CollidableOffset", "CollidableShape", "Collision",
    "CollisionCollection", "CollisionSensor", "CollisionSpace", "Color", "ColorChaser", "ColorDamper",
    "ColorInterpolator", "ColorRGBA", "Comment", "ComposedCubeMapTexture", "ComposedShader", "ComposedTexture3D",
    "ComposedVolumeStyle", "Cone", "ConeEmitter", "Contact", "Contour2D", "ContourPolyline2D", "Convolver",
    "Coordinate", "CoordinateChaser", "CoordinateDamper", "CoordinateDouble", "CoordinateInterpolator",
    "CoordinateInterpolator2D", "Cylinder", "CylinderSensor", "DISEntityManager", "DISEntityTypeMapping", "Delay",
    "DirectionalLight", "Disk2D", "DoubleAxisHingeJoint", "DynamicsCompressor", "EXPORT", "EaseInEaseOut",
    "EdgeEnhancementVolumeStyle", "ElevationGrid", "EnvironmentLight", "EspduTransform", "ExplosionEmitter",
    "ExternProtoDeclare", "Extrusion", "FillProperties", "FloatVertexAttribute", "Fog", "FogCoordinate",
    "FontLibrary", "FontStyle", "ForcePhysicsModel", "Gain", "GaussianSplats", "GeneratedCubeMapTexture",
    "GeoCoordinate", "GeoElevationGrid", "GeoLOD", "GeoLocation", "GeoMetadata", "GeoOrigin",
    "GeoPositionInterpolator", "GeoProximitySensor", "GeoTouchSensor", "GeoTransform", "GeoViewpoint", "Group",
    "HAnimDisplacer", "HAnimHumanoid", "HAnimJoint", "HAnimMotion", "HAnimPose", "HAnimSegment", "HAnimSite",
    "IMPORT", "IS", "ImageCubeMapTexture", "ImageTexture", "ImageTexture3D", "IndexedFaceSet", "IndexedLineSet",
    "IndexedQuadSet", "IndexedTriangleFanSet", "IndexedTriangleSet", "IndexedTriangleStripSet", "Inline",
    "InlineGeometry", "IntegerSequencer", "IntegerTrigger", "IsoSurfaceVolumeData", "KeySensor", "LOD", "Layer",
    "LayerSet", "Layout", "LayoutGroup", "LayoutLayer", "LinePickSensor", "LineProperties", "LineSet",
    "ListenerPointSource", "LoadSensor", "LocalFog", "MFNode", "Material", "Matrix3VertexAttribute",
    "Matrix4VertexAttribute", "MetadataBoolean", "MetadataDouble", "MetadataFloat", "MetadataInteger", "MetadataSet",
    "MetadataString", "MicrophoneSource", "MotorJoint", "MovieTexture", "MultiTexture", "MultiTextureCoordinate",
    "MultiTextureTransform", "NavigationInfo", "Normal", "NormalInterpolator", "NurbsCurve", "NurbsCurve2D",
    "NurbsOrientationInterpolator", "NurbsPatchSurface", "NurbsPositionInterpolator", "NurbsSet",
    "NurbsSurfaceInterpolator", "NurbsSweptSurface", "NurbsSwungSurface", "NurbsTextureCoordinate",
    "NurbsTrimmedSurface", "OpacityMapVolumeStyle", "OrientationChaser", "OrientationDamper",
    "OrientationInterpolator", "OrthoViewpoint", "OscillatorSource", "PackagedShader", "ParticleSystem",
    "PeriodicWave", "PhysicalMaterial", "PickableGroup", "PixelTexture", "PixelTexture3D", "PlaneSensor",
    "PointEmitter", "PointLight", "PointPickSensor", "PointProperties", "PointSet", "Polyline2D", "PolylineEmitter",
    "Polypoint2D", "PositionChaser", "PositionChaser2D", "PositionDamper", "PositionDamper2D", "PositionInterpolator",
    "PositionInterpolator2D", "PrimitivePickSensor", "ProgramShader", "ProjectionVolumeStyle", "ProtoBody",
    "ProtoDeclare", "ProtoInstance", "ProtoInterface", "ProximitySensor", "QuadSet", "ROUTE", "ReceiverPdu",
    "Rectangle2D", "RenderedTexture", "RigidBody", "RigidBodyCollection", "SFNode", "ScalarChaser", "ScalarDamper",
    "ScalarInterpolator", "Scene", "ScreenFontStyle", "ScreenGroup", "Script", "SegmentedVolumeData",
    "ShadedVolumeStyle", "ShaderPart", "ShaderProgram", "Shape", "SignalPdu", "SilhouetteEnhancementVolumeStyle",
    "SingleAxisHingeJoint", "SliderJoint", "Sound", "SpatialSound", "Sphere", "SphereSensor",
    "SplinePositionInterpolator", "SplinePositionInterpolator2D", "SplineScalarInterpolator", "SpotLight",
    "SquadOrientationInterpolator", "StaticGroup", "StreamAudioDestination", "StreamAudioSource", "StringSensor",
    "SurfaceEmitter", "Switch", "Tangent", "TexCoordChaser2D", "TexCoordDamper2D", "Text", "TextureBackground",
    "TextureCoordinate", "TextureCoordinate3D", "TextureCoordinate4D", "TextureCoordinateGenerator",
    "TextureProjector", "TextureProjectorParallel", "TextureProperties", "TextureTransform", "TextureTransform3D",
    "TextureTransformMatrix3D", "TimeSensor", "TimeTrigger", "ToneMappedVolumeStyle", "TouchSensor", "Transform",
    "TransformInfo", "TransformSensor", "TransmitterPdu", "TriangleFanSet", "TriangleSet", "TriangleSet2D",
    "TriangleStripSet", "TwoSidedMaterial", "UniversalJoint", "UnlitMaterial", "Viewpoint", "ViewpointGroup",
    "Viewport", "VisibilitySensor", "VolumeData", "VolumeEmitter", "VolumePickSensor", "WaveShaper",
    "WindPhysicsModel", "WorldInfo", "X3D", "component", "connect", "field", "fieldValue", "head", "meta", "unit",
))
