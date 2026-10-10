from input_engine import InputEngine

engine = InputEngine(
    ".",
    log=print
)

print()
print("========== INPUT TEST ==========")
print()

print("Initial status:")
print(engine.status())

print()
print("Enabling Input Mode...")
print()

if engine.enable():

    print()
    print("SUCCESS: Input Mode is ON")
    print()
    print("Status:")
    print(engine.status())

    input(
        "\nPress ENTER to restore your original settings..."
    )

    print()
    print("Restoring...")
    engine.disable()

    print()
    print("Final status:")
    print(engine.status())

else:

    print()
    print("FAILED: Input Mode did not enable.")