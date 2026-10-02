"""Kit per i blockout Blender del pannello superiore.

- ``spec``        schema, default e validazione della spec JSON (senza bpy)
- ``moto``        easing, camera, percorsi, camminata: matematica pura (senza bpy)
- ``kit``         costruzione della scena in Blender (richiede bpy)
- ``build_shot``  entrypoint per ``blender -b --python``
- ``confronta``   griglia di confronto clip AI / blockout (senza bpy)

Vedi ``SPEC.md`` per il formato della spec.
"""
