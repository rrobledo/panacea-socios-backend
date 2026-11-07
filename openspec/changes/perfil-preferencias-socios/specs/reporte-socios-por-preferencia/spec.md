## ADDED Requirements

### Requirement: Buscar socios por producto o preferencia
`GET /reportes/preferencias?q=<texto>` SHALL devolver los socios cuyo perfil coincide con el texto buscado, sin distinguir mayúsculas, minúsculas ni acentos, como coincidencia parcial ("chocolate" encuentra "chocolate amargo" y "Alfajor de Chocolate"). La búsqueda MUST cubrir etiquetas, categorías favoritas y productos favoritos, y MUST cubrir también el resumen solo cuando se envía `incluir_resumen=true`. Cada resultado MUST incluir los datos de contacto del socio (id, nombre y apellido, DNI, email, teléfono), las coincidencias encontradas (campo y valor) y la fecha del perfil. Los resultados MUST ordenarse por relevancia (coincidencia en etiqueta > producto > categoría > resumen) y después por nombre, y MUST paginarse con `skip` y `limit` (por defecto 100, máximo 500). Requiere un usuario autenticado. `q` es obligatorio y MUST tener al menos 2 caracteres.

#### Scenario: Coincidencia por etiqueta sin acentos
- **WHEN** se busca `q=limon` y un socio tiene la etiqueta "limón"
- **THEN** el socio aparece con la coincidencia `{campo: "etiqueta", valor: "limón"}`

#### Scenario: Coincidencia por producto
- **WHEN** se busca `q=amargo` y un socio tiene entre sus productos favoritos "Alfajor chocolate amargo"
- **THEN** el socio aparece con la coincidencia de producto

#### Scenario: Orden por relevancia
- **WHEN** un socio coincide por etiqueta y otro solo por categoría
- **THEN** el que coincide por etiqueta aparece primero

#### Scenario: Resumen solo si se pide
- **WHEN** el texto buscado aparece solo en el resumen de un socio
- **THEN** ese socio aparece únicamente si la consulta incluye `incluir_resumen=true`

#### Scenario: Texto muy corto
- **WHEN** se busca con `q` de menos de 2 caracteres
- **THEN** responde 422

#### Scenario: Sin resultados
- **WHEN** ningún perfil coincide
- **THEN** responde 200 con una lista vacía

### Requirement: Listar las etiquetas de preferencia
`GET /reportes/preferencias/etiquetas` SHALL devolver todas las etiquetas presentes en los perfiles con la cantidad de socios que tiene cada una, ordenadas de mayor a menor cantidad y después alfabéticamente, para que el frontend ofrezca las búsquedas disponibles. Requiere un usuario autenticado.

#### Scenario: Conteo de etiquetas
- **WHEN** tres socios tienen la etiqueta "chocolate" y uno tiene "sin tacc"
- **THEN** la respuesta contiene `{etiqueta: "chocolate", socios: 3}` antes que `{etiqueta: "sin tacc", socios: 1}`
