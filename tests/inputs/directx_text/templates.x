xof 0302txt 0032

template Vector {
 <3d82ab5e-62da-11cf-ab39-0020af71e433>
 FLOAT x;
 FLOAT y;
 FLOAT z;
}

template MeshFace {
 <3d82ab5f-62da-11cf-ab39-0020af71e433>
 DWORD nFaceVertexIndices;
 array DWORD faceVertexIndices[nFaceVertexIndices];
}

template Mesh {
 <3d82ab44-62da-11cf-ab39-0020af71e433>
 DWORD nVertices;
 array Vector vertices[nVertices];
 DWORD nFaces;
 array MeshFace faces[nFaces];
 [...]
}

Mesh Triangle {
 3;
 0;0;0;,
 2;0;0;,
 0;4;-3;;
 1;
 3;0,1,2;;
 MeshTextureCoords {
  3;
  0;0;,
  1;0;,
  0;1;;
 }
 MeshMaterialList {
  1;
  1;
  0;;
  Material Red {
   1;0;0;1;;
   0;
   0;0;0;;
   0;0;0;;
  }
 }
}
