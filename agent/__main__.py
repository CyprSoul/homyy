from .main import main

# Перевірка обов'язкова: процес «живої сфери» на Windows імпортує цей файл повторно.
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nБувай! 👋")
