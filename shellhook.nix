{
  nix,
  nix-pyenv-directory,
  pyenv,
  usingPython,
  persist,
  inputDerivation ? "",
  ...
}:
let
  optionalCommentOut = if persist then "" else "#";
  sitePackages = usingPython.sitePackages;
in
''
  if [[ $name == nix-shell ]]; then
      cd ${builtins.toString ./.}
  fi

  # ensure the nix-pyenv directory exists
  if [[ ! -d ${nix-pyenv-directory} ]]; then mkdir ${nix-pyenv-directory}; fi
  if [[ ! -d ${nix-pyenv-directory}/lib ]]; then mkdir ${nix-pyenv-directory}/lib; fi
  if [[ ! -d ${nix-pyenv-directory}/bin ]]; then mkdir ${nix-pyenv-directory}/bin; fi

  ensure_symlink() {
      local link_path="$1"
      local target_path="$2"
      if [[ -L "$link_path" ]] && [[ "$(readlink "$link_path")" = "$target_path" ]]; then
          return 0
      fi
      rm -f "$link_path" > /dev/null 2>&1
      ln -s "$target_path" "$link_path"
  }

  # creating python library symlinks
  for file in ${pyenv}/${sitePackages}/*; do
      basefile=$(basename $file)
      if [ -d "$file" ]; then
          if [[ "$basefile" != *dist-info && "$basefile" != __pycache__ ]]; then
              ensure_symlink "${nix-pyenv-directory}/lib/$basefile" $file
          fi
      else
          # the typing_extensions.py will make the vscode type checker not working!
          if [[ $basefile == *.so ]] || ([[ $basefile == *.py ]] && [[ $basefile != typing_extensions.py ]]); then
              ensure_symlink "${nix-pyenv-directory}/lib/$basefile" $file
          fi
      fi
  done
  for file in ${nix-pyenv-directory}/lib/*; do
      if [[ -L "$file" ]] && [[ "$(dirname $(readlink "$file"))" != "${pyenv}/${sitePackages}" ]]; then
          rm -f "$file"
      fi
  done

  # ensure the typing_extensions.py is not in the lib directory
  rm ${nix-pyenv-directory}/lib/typing_extensions.py > /dev/null 2>&1

  # add python executable to the bin directory
  ensure_symlink "${nix-pyenv-directory}/bin/python" ${pyenv}/bin/python
  export PATH=${nix-pyenv-directory}/bin:$PATH

  ${optionalCommentOut} ${nix}/bin/nix-store --add-root ${nix-pyenv-directory}/.nix-shell-inputs --realise ${inputDerivation}
''
