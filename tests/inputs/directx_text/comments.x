xof 0302txt 0032
# Between the header and the mesh. Braces in comments are ignored: { }
Mesh CommentedTriangle { # After the mesh opening brace.
 3; # Vertex count.
 0;0;0;, # After a complete vertex.
 2; # Between components of one vertex.
 0;0;,
 # Between vertex records.
 0;4;-3;;

 1; # Face count.
 3;0, # Between face indices.
 1,2;;

 MeshTextureCoords {
  # Inside a nested block.
  3;
  0;0;,
  1;0;, # After UV coordinates.
  0;1;;
 } # After a nested closing brace.
 MeshMaterialList {
  1;
  1;
  0;;
  Material Red {
   1;0;0;1;; # After the diffuse color.
   0;
   0;0;0;;
   0;0;0;;
  }
 }
}
# After the mesh.
