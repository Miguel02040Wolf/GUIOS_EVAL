"""Punto de entrada: python -m guios"""
from guios.app import app

print("\n  GUIOS EVAL listo. Abre en tu navegador:  http://127.0.0.1:5000\n"
      "  Usuario de prueba: lider@guios.edu.ec  /  contraseña: guios2026\n")
app.run(host="127.0.0.1", port=5000, debug=False)
