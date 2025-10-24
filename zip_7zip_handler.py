from PyQt5.QtWidgets import QFileDialog
#import struct
from PyQt5.QtWidgets import QFileDialog, QMessageBox
import zipfile
import py7zr
import os

# ---------- ZIP ----------
def extract_zip():
    file_path, _ = QFileDialog.getOpenFileName(None, "Seleccionar archivo ZIP", "", "Zip Files (*.zip)")
    if not file_path:
        return
    
    extract_path = file_path.replace(".zip", "_extracted")
    with zipfile.ZipFile(file_path, 'r') as zip_ref:
        zip_ref.extractall(extract_path)

    QMessageBox.information(None, "Éxito", f"Archivos extraídos en:\n{extract_path}")


def create_zip():
    files, _ = QFileDialog.getOpenFileNames(None, "Seleccionar archivos para comprimir")
    if not files:
        return

    save_path, _ = QFileDialog.getSaveFileName(None, "Guardar ZIP", "", "Zip Files (*.zip)")
    if not save_path:
        return

    with zipfile.ZipFile(save_path, 'w') as zip_ref:
        for f in files:
            zip_ref.write(f, os.path.basename(f))  # guardar solo nombre, no ruta completa

    QMessageBox.information(None, "Éxito", f"ZIP creado en:\n{save_path}")


# ---------- 7Z ----------
def extract_7z():
    file_path, _ = QFileDialog.getOpenFileName(None, "Seleccionar archivo 7z", "", "7z Files (*.7z)")
    if not file_path:
        return
    
    extract_path = file_path.replace(".7z", "_extracted")
    with py7zr.SevenZipFile(file_path, mode='r') as archive:
        archive.extractall(path=extract_path)

    QMessageBox.information(None, "Éxito", f"Archivos extraídos en:\n{extract_path}")


def create_7z():
    files, _ = QFileDialog.getOpenFileNames(None, "Seleccionar archivos para comprimir")
    if not files:
        return

    save_path, _ = QFileDialog.getSaveFileName(None, "Guardar 7z", "", "7z Files (*.7z)")
    if not save_path:
        return

    with py7zr.SevenZipFile(save_path, 'w') as archive:
        for f in files:
            archive.write(f, arcname=os.path.basename(f))

    QMessageBox.information(None, "Éxito", f"7z creado en:\n{save_path}")


# De momento descartado
#def read_rar(file_path):
#    with open(file_path, "rb") as file:
#        data = file.read()
#        # Leer los primeros bytes (por ejemplo, 7 para la firma RAR)
#        header = data[:7]
#        print(f"Header: {header}")
#        
#        # Extraer un bloque de datos, por ejemplo:
#        signature = struct.unpack("<4s", data[:4])  # Leer 4 bytes como cadena
#        print(f"Signature: {signature}")
#
#def write_rar_header(output_file):
#    with open(output_file, "wb") as file:
#        # Escribir un encabezado ficticio (esto NO es realista para .rar)
#        file.write(b"RAR!")  # Firma del archivo RAR
#        file.write(struct.pack("<H", 0x0001))  # Versión ficticia
#        print("Encabezado RAR escrito.")
#
#def lzss_compress(input_data):
#    compressed_data = []
#    window = []
#    
#    for byte in input_data:
#        if byte in window:
#            # Generar un puntero al bloque existente
#            index = window.index(byte)
#            compressed_data.append((index, len(byte)))
#        else:
#            # Agregar byte literal
#            compressed_data.append(byte)
#        window.append(byte)
#        if len(window) > 4096:  # Limitar el tamaño de la ventana
#            window.pop(0)
#    return compressed_data