{
  description = "Environment for DesloppiFlutter";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    nixpkgs-stable.url = "github:NixOS/nixpkgs/nixos-24.11";
  };
  outputs = { self, nixpkgs, nixpkgs-stable }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in {
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [
          (pkgs.python3.withPackages (ps: with ps; [
            pytest
            pyyaml
            pillow
          ]))
        ];
        shellHook = ''
          export PATH="$PATH:$HOME/.pub-cache/bin"
        '';
      };
    };
}
