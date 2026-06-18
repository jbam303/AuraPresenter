import os
import subprocess
import sys
import platform

def run_command(cmd, cwd=None, ignore_errors=False):
    print(f"Running: {' '.join(cmd)}")
    # On Windows, tools like pnpm are .cmd scripts that need shell=True
    use_shell = platform.system() == 'Windows'
    result = subprocess.run(cmd, cwd=cwd, shell=use_shell)
    if result.returncode != 0 and not ignore_errors:
        print(f"Error: Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)

def build():
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(backend_dir)
    frontend_dir = os.path.join(project_dir, 'frontend')
    releases_dir = os.path.join(project_dir, 'releases')

    print("=== Step 1: Building Frontend ===")
    run_command(['pnpm', 'install'], cwd=frontend_dir)
    run_command(['pnpm', 'run', 'build'], cwd=frontend_dir)

    print("=== Step 2: Packaging Backend ===")
    
    pyinstaller_cmd = [
        'pyinstaller',
        '--noconfirm',
        '--clean',
        '--distpath', releases_dir,
        'AuraPresenter.spec'
    ]

    # Use the venv's pyinstaller if it exists
    venv_bin = os.path.join(backend_dir, '.venv', 'bin' if platform.system() != 'Windows' else 'Scripts')
    pyinstaller_path = os.path.join(venv_bin, 'pyinstaller')
    
    if os.path.exists(pyinstaller_path):
        pyinstaller_cmd[0] = pyinstaller_path

    run_command(pyinstaller_cmd, cwd=backend_dir)

    # Clean xattrs and sign at the end to prevent Gatekeeper issues
    if platform.system() == 'Darwin':
        app_bundle = os.path.join(releases_dir, 'AuraPresenter.app')
        print("Cleaning extended attributes and signing...")
        run_command(['find', app_bundle, '-name', '.DS_Store', '-delete'], ignore_errors=True)
        run_command(['dot_clean', '-m', app_bundle], ignore_errors=True)
        run_command(['xattr', '-cr', app_bundle], ignore_errors=True)
        run_command(['xattr', '-d', 'com.apple.FinderInfo', app_bundle], ignore_errors=True)
        run_command(['xattr', '-d', 'com.apple.FinderInfo', os.path.join(app_bundle, 'Contents')], ignore_errors=True)
        run_command(['codesign', '-s', '-', '--force', '--deep', app_bundle])

    print(f"=== Build Complete! Executable is in {releases_dir} ===")

if __name__ == '__main__':
    build()
