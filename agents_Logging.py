import agents
import inspect
import logging

# Configure logging to output to the console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logging.info("--- Inspecting the 'agents' module ---")
logging.info(f"Available names directly in the 'agents' module: {dir(agents)}")

logging.info("\n--- Inspecting members of the 'agents' module ---")
for name, obj in inspect.getmembers(agents):
    if not name.startswith("__"):
        logging.info(f"Name: {name}, Type: {type(obj)}")
        if hasattr(obj, '__doc__') and obj.__doc__:
            logging.info(f"  Docstring: {obj.__doc__.strip()}")
        if inspect.isclass(obj):
            logging.info(f"  --- Inspecting members of class '{name}' ---")
            for member_name, member_obj in inspect.getmembers(obj):
                if not member_name.startswith("__"):
                    logging.info(f"    Member Name: {member_name}, Type: {type(member_obj)}")
                    if hasattr(member_obj, '__doc__') and member_obj.__doc__:
                        logging.info(f"      Member Docstring: {member_obj.__doc__.strip()}")
            logging.info(f"  --- End of class '{name}' inspection ---")
        elif inspect.isfunction(obj):
            signature = inspect.signature(obj)
            logging.info(f"  Signature: {signature}")
        logging.info("-" * 40)