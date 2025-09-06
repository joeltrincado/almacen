# SolucionAlmacen app

## Run the app

### uv

Run as a desktop app:

```
uv run flet run
```

Run as a web app:

```
uv run flet run --web
```

### Poetry

Install dependencies from `pyproject.toml`:

```
poetry install
```

Run as a desktop app:

```
poetry run flet run
```

Run as a web app:

```
poetry run flet run --web
```

For more details on running the app, refer to the [Getting Started Guide](https://flet.dev/docs/getting-started/).

## Build the app

### Android

```
flet build apk -v
```

For more details on building and signing `.apk` or `.aab`, refer to the [Android Packaging Guide](https://flet.dev/docs/publish/android/).

### iOS

```
flet build ipa -v
```

For more details on building and signing `.ipa`, refer to the [iOS Packaging Guide](https://flet.dev/docs/publish/ios/).

### macOS

```
flet build macos -v
```

For more details on building macOS package, refer to the [macOS Packaging Guide](https://flet.dev/docs/publish/macos/).

### Linux

```
flet build linux -v
```

For more details on building Linux package, refer to the [Linux Packaging Guide](https://flet.dev/docs/publish/linux/).

### Windows

```
flet build windows -v
```

For more details on building Windows package, refer to the [Windows Packaging Guide](https://flet.dev/docs/publish/windows/).



este es mi codigo actualizado, quiero hacer algunos cambios, quiero que al abrir la app no me salgan directamente los almacenes, sino que salgan solamente cuando presiono en el boton ver almacenes. Quiero que en la vista principal que sale del menu de Inicio de dashboard, sea capturar datos, aparezcan 2 contenedores similar al de almacen, que tenga un íconno y cada uno sea para agregar entrada o salida a almacen, luego aparezca un alert que va a contener un dropdown para seleccionar uno de los almacenes registrados, y despues un texfield para escaner producto. El alert va a decir arriba si es para dar entrada o salida. En el mismo alert cada producto es