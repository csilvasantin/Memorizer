# Yarig.ai — Mapa completo de funcionalidades y API

## Secciones de la plataforma

| Sección | URL | Descripción |
|---------|-----|-------------|
| Mis tareas | /tasks | Tareas del día actual, iniciar/parar/cerrar |
| Historial de tareas | /tasks/history | Histórico de todas las tareas |
| Peticiones | /tasks/requests | Peticiones de tareas entre usuarios |
| Puntuación | /score | Calendario de puntuación diaria |
| Estadísticas año | /personal/stats | Stats anuales del usuario |
| Puntos del mes | /personal/scoring | Puntos acumulados último mes |
| Misiones (Ranking) | /productivity/ranking | Ranking de productividad del equipo |
| Objetivos equipo | /productivity/dedication | Objetivos y dedicación del equipo |
| Clientes | /productivity/customers | Clientes y oportunidades |
| Proyectos | /projects | Gestión de proyectos |
| Reuniones | /meetings | Reuniones y eventos |
| Muro | /wall | Feed de actividad / emergencias |
| Dashboard | /dashboard | Panel principal |
| Perfil | /user/profile | Perfil del usuario |
| Admin | /admin | Panel de administración |
| Facturación | /billing/bills, /billing/inout | Facturas y entradas/salidas |
| Marca/RRSS | /brand/social_media | Gestión de redes sociales |

## API JSON Endpoints detallados

### Tareas
| Endpoint | Params | Descripción |
|----------|--------|-------------|
| json_get_current_day_tasks_and_journey_info | (none) | Tareas del día + info jornada |
| json_add_tasks | tasks: "tmpId#$#estimation#$#description#$#projectId@$@" | Añadir tareas (formato concatenado) |
| json_update_task | task, period, description, project | Actualizar tarea |
| json_delete_task | id | Eliminar tarea |
| json_get_and_open_task | tid, finished | Abrir/iniciar tarea |
| json_close_task | data(serialized) | Cerrar/finalizar tarea |
| json_add_task_from_other | ? | Añadir tarea desde otra fuente |

### Peticiones entre usuarios
| Endpoint | Params | Descripción |
|----------|--------|-------------|
| json_add_request | ? | Crear petición (sugerencia/petición/urgencia) |
| json_get_task_request | ? | Obtener detalle de petición |
| json_get_unread_requests_by_user | (none) | Peticiones no leídas |
| json_get_unread_requests_by_user_and_priority | ? | Peticiones por prioridad |
| json_update_state_task_request | id, state (1=leída, 2=aceptada) | Cambiar estado petición |
| json_add_open_task_from_task_request | ? | Crear tarea desde petición |

### Jornada / Fichaje
| Endpoint | Params | Descripción |
|----------|--------|-------------|
| clocking/json_add_clocking | type: 0=entrada, 1=salida; todo: texto | Fichar entrada/salida |
| clocking_extra/json_add_clocking_extra | type: 0=inicio, 1=fin | Horas extras |

### Interrupciones
| Endpoint | Params | Descripción |
|----------|--------|-------------|
| interruption/json_add_interruption | tid, uid, start, note | Interrupción por compañero |
| interruption/json_add_customer_interruption | tid, uid, start, note | Interrupción por cliente |

### Puntuación
| Endpoint | Params | Descripción |
|----------|--------|-------------|
| score/json_user_score | (none) | Puntuación actual (devuelve int) |

### Estado de trabajo
| Endpoint | Params | Descripción |
|----------|--------|-------------|
| working_state/json_change_state | state, place | Cambiar estado (6=trabajando, 12=fin, etc.) |

### Notificaciones
| Endpoint | Params | Descripción |
|----------|--------|-------------|
| system_notification/json_get_user_notifications | (none) | Obtener notificaciones |
| system_notification/json_change_notification_state | ? | Marcar notificación leída |
| system_notification/json_wall_all_read | (none) | Marcar todo como leído |

### Usuarios y proyectos
| Endpoint | Params | Descripción |
|----------|--------|-------------|
| user/json_get_customers_and_mates_like | term | Buscar clientes y compañeros |
| projects/json_get_projects_like_by_customer_and_order | term, customer | Buscar proyectos |

## Tipos de petición
- type 1: Sugerencia (verde)
- type 2: Petición (amarillo)
- type 3: Urgencia (rojo)

## Datos clave
- Carlos Silva: id_user=14, id_company=22
- Cliente Admira: id_customer=2396
- Proyecto Admira: id_project=312
- 23 compañeros registrados

## Autenticación
- Login: POST /registration/login (email + password + submit=Entrar)
- Requiere GET previo para establecer cisession cookie
- Session cookie: cisession (rotativa por request, usar CookieJar)
- SSL: certificado incompleto, requiere ssl=False
