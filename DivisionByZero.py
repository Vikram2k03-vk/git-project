def divide(dividend, divisor):
    try:
        result = dividend / divisor
        print(f"The result is: {result}")
    except ZeroDivisionError:
        print("Error: Cannot divide by zero!")
    except TypeError:
        print("Error: Invalid input types for division.")
    finally:
        print("Division attempt completed.")

#divide(10, 2)
divide(10, 0)
#divide("abc", 5)