# Shared code

Reserved for code used by more than one service (JWT verification, DB models, config loading).
Leave empty until two services actually need the same thing. Then decide how to package it
(for example a small installable package copied into each Docker build).
