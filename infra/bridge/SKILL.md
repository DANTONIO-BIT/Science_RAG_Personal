---
name: Bridge to Cloud
description: "Envía una consulta compleja a un modelo en la nube grande tras pedirle confirmación obligatoria al usuario."
---

# Bridge Cloud Skill

Cuando determines que un problema razonativo (matemáticas avanzadas, arquitectura muy compleja que excede tus capacidades, etc) requiere escalar al Agente General (modelo Cloud grande), DEBES usar esta skill.

**Regla Estricta**: No usarás bash para resolver el problema ni inventarás resultados si el nivel de confianza baja. Ejecutarás directamente este script:

## Ejecución en Terminal

Usa la herramienta nativa de `bash` para ejecutar e interactuar de la siguiente manera:
```bash
python3 /Users/diego/Desktop/Proyectos_ongoing/_agent/skills/bridge/bridge_cloud.py "RESUMEN EXACTO Y DETALLADO DEL PROBLEMA AQUI. NO INCLUYAS CLAVES, APIS NI DATOS PERSONALES."
```

## Manejo de Respuesta
1. Una vez ejecutado, el script en el entorno le preguntará al usuario Y/N.
2. Tú (el agente OpenCode) simplemente espera a que la salida de la terminal indique "✅ Respuesta recibida desde Cloud" o "ACCESO DENEGADO".
3. Luego, toma la salida mostrada y úsala para continuar el trabajo localmente. No sigas intentando repetir el proceso si fue denegado.
