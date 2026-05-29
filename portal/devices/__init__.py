"""V6 device subsystem — simulated medical devices that join a session.

Three device kinds are supported:

- ``pump_iv``        IV infusion pump  (reference device: Alaris)
- ``pump_enteral``   Enteral feed pump (reference device: Kangaroo OMNI)
- ``cabinet``        Dispensing cabinet (reference device: BD Pyxis MedStation ES)

Each device is one *engine* (Layer A — state machine, alarm subsystem,
input/render glue in ``engine/``) plus one *skin* — an SVG overlay and a
``spec.json`` declaring screens, controls, alarms, and any catalog data
(drug library for pumps, medication catalog for cabinets). The engine is
device-kind-specific; the skin is device-model-specific. Adding a new
model = drop another folder under ``pumps/`` or ``cabinets/`` with a new
``spec.json`` + ``skin.svg``.
"""
