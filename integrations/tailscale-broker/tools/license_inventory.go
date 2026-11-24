// Command license_inventory records license and notice files for the Go module
// dependency closure selected by the current GOOS, GOARCH, and build tags.
//
// It is a reproducible file inventory, not an SPDX classifier or legal audit.
// Missing license files are explicitly listed for human review and fail the
// command after the inventory has been written.
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

const (
	defaultOutput      = "licenses"
	defaultLicenseRoot = "dependency_licenses"
	noticeFileName     = "THIRD_PARTY_NOTICES.md"
	maxLicenseFileSize = 4 << 20
)

type packageInfo struct {
	ImportPath string
	Module     *moduleInfo
}

type moduleInfo struct {
	Path    string
	Version string
	Dir     string
	Main    bool
	Replace *moduleInfo
}

type dependency struct {
	Path        string
	Version     string
	Dir         string
	Replacement string
	Files       []licenseFile
}

type licenseFile struct {
	ModulePath  string
	Version     string
	Relative    string
	Destination string
	Hash        string
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	var (
		outputPath = flag.String("output", defaultOutput, "output directory for the notice and copied license texts")
		packageArg = flag.String("package", ".", "Go package pattern whose built dependencies are inventoried")
		tagsArg    = flag.String("tags", "", "comma-separated build tags passed to go list")
		goosArg    = flag.String("goos", "", "GOOS used to select the built dependency closure")
		goarchArg  = flag.String("goarch", "", "GOARCH used to select the built dependency closure")
	)
	flag.Parse()

	packages, err := listPackages(context.Background(), *packageArg, *tagsArg, *goosArg, *goarchArg)
	if err != nil {
		return err
	}
	dependencies := collectDependencies(packages)
	if len(dependencies) == 0 {
		return fmt.Errorf("go list returned no third-party module dependencies")
	}

	outputRoot := filepath.Clean(*outputPath)
	if outputRoot == "." || outputRoot == string(filepath.Separator) ||
		outputRoot == filepath.VolumeName(outputRoot)+string(filepath.Separator) ||
		(!filepath.IsAbs(outputRoot) && (outputRoot == ".." || strings.HasPrefix(outputRoot, ".."+string(filepath.Separator)))) {
		return fmt.Errorf("output must be a non-root directory")
	}
	licenseRoot := filepath.Join(outputRoot, defaultLicenseRoot)
	if err := os.RemoveAll(licenseRoot); err != nil {
		return fmt.Errorf("replace generated dependency license directory: %w", err)
	}
	if err := os.MkdirAll(licenseRoot, 0o755); err != nil {
		return fmt.Errorf("create generated license directory: %w", err)
	}

	missingModules := make([]string, 0)
	for index := range dependencies {
		dependency := &dependencies[index]
		files, err := collectLicenseFiles(dependency, licenseRoot)
		if err != nil {
			return err
		}
		dependency.Files = files
		if len(files) == 0 {
			missingModules = append(missingModules, dependency.Path+"@"+dependency.Version)
		}
	}

	goVersion, goFiles, err := collectGoToolchainNotices(outputRoot)
	if err != nil {
		return err
	}
	content := renderInventory(dependencies, *packageArg, *tagsArg, *goosArg, *goarchArg, goVersion, goFiles, len(missingModules))
	if err := os.MkdirAll(outputRoot, 0o755); err != nil {
		return fmt.Errorf("create output directory: %w", err)
	}
	if err := os.WriteFile(filepath.Join(outputRoot, noticeFileName), content, 0o644); err != nil {
		return fmt.Errorf("write notice inventory: %w", err)
	}
	fmt.Printf("inventoried %d Go modules; %d have no recognized license or notice file\n", len(dependencies), len(missingModules))
	if len(missingModules) > 0 {
		return fmt.Errorf("no recognized license or notice for runtime module(s) %s; review %s", strings.Join(missingModules, ", "), filepath.Join(outputRoot, noticeFileName))
	}
	return nil
}

func listPackages(ctx context.Context, packagePattern, tags, goos, goarch string) ([]packageInfo, error) {
	args := []string{"list", "-mod=readonly", "-deps", "-json"}
	if tags != "" {
		args = append(args, "-tags="+tags)
	}
	args = append(args, packagePattern)
	command := exec.CommandContext(ctx, "go", args...)
	if goos != "" || goarch != "" {
		environment := os.Environ()
		for _, override := range []struct{ name, value string }{{"GOOS", goos}, {"GOARCH", goarch}} {
			if override.value == "" {
				continue
			}
			prefix := override.name + "="
			filtered := environment[:0]
			for _, entry := range environment {
				if !strings.HasPrefix(strings.ToUpper(entry), prefix) {
					filtered = append(filtered, entry)
				}
			}
			environment = append(filtered, prefix+override.value)
		}
		command.Env = environment
	}
	output, err := command.Output()
	if err != nil {
		return nil, fmt.Errorf("go list dependency closure failed: %w", err)
	}
	decoder := json.NewDecoder(bytes.NewReader(output))
	var packages []packageInfo
	for {
		var item packageInfo
		if err := decoder.Decode(&item); err != nil {
			if err == io.EOF {
				break
			}
			return nil, fmt.Errorf("decode go list output: %w", err)
		}
		packages = append(packages, item)
	}
	return packages, nil
}

func collectDependencies(packages []packageInfo) []dependency {
	byModule := make(map[string]dependency)
	for _, item := range packages {
		module := item.Module
		if module == nil || module.Main {
			continue
		}
		path, version, directory, replacement := module.Path, module.Version, module.Dir, ""
		if module.Replace != nil {
			replacement = module.Replace.Path
			if module.Replace.Version != "" {
				replacement += "@" + module.Replace.Version
			}
			if module.Replace.Dir != "" {
				directory = module.Replace.Dir
			}
		}
		if path == "" || directory == "" {
			continue
		}
		key := path + "@" + version
		byModule[key] = dependency{Path: path, Version: version, Dir: directory, Replacement: replacement}
	}
	dependencies := make([]dependency, 0, len(byModule))
	for _, dependency := range byModule {
		dependencies = append(dependencies, dependency)
	}
	sort.Slice(dependencies, func(i, j int) bool {
		if dependencies[i].Path != dependencies[j].Path {
			return dependencies[i].Path < dependencies[j].Path
		}
		return dependencies[i].Version < dependencies[j].Version
	})
	return dependencies
}

func collectLicenseFiles(dependency *dependency, licenseRoot string) ([]licenseFile, error) {
	root := filepath.Clean(dependency.Dir)
	files := make(map[string]struct{})
	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, fmt.Errorf("read module directory %s: %w", dependency.Path, err)
	}
	var licenseDirectories []string
	for _, entry := range entries {
		if entry.Type()&os.ModeSymlink != 0 {
			continue
		}
		path := filepath.Join(root, entry.Name())
		if entry.IsDir() {
			name := strings.ToLower(entry.Name())
			if name == "licenses" || name == "licences" || name == "license" || name == "licence" ||
				name == "vendor" || name == "third_party" || name == "third-parties" {
				licenseDirectories = append(licenseDirectories, path)
			}
			continue
		}
		if isLicenseName(entry.Name()) {
			files[path] = struct{}{}
		}
	}
	if dependency.Path == "tailscale.com" {
		// Tailscale keeps a few independently licensed test-fork and header
		// files outside its usual licenses/vendor/third_party directories.
		for _, relative := range []string{"tempfork", "tstest", "derp/xdp/headers"} {
			directory := filepath.Join(root, filepath.FromSlash(relative))
			info, err := os.Stat(directory)
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			if err != nil {
				return nil, fmt.Errorf("inspect nested license directory for %s: %w", dependency.Path, err)
			}
			if info.IsDir() {
				licenseDirectories = append(licenseDirectories, directory)
			}
		}
	}
	for _, directory := range licenseDirectories {
		err := filepath.WalkDir(directory, func(path string, entry os.DirEntry, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}
			if entry.Type()&os.ModeSymlink != 0 || entry.IsDir() {
				return nil
			}
			if isLicenseName(entry.Name()) {
				files[path] = struct{}{}
			}
			return nil
		})
		if err != nil {
			return nil, fmt.Errorf("scan license directory for %s: %w", dependency.Path, err)
		}
	}

	paths := make([]string, 0, len(files))
	for path := range files {
		paths = append(paths, path)
	}
	sort.Strings(paths)
	result := make([]licenseFile, 0, len(paths))
	for _, path := range paths {
		info, err := os.Stat(path)
		if err != nil {
			return nil, fmt.Errorf("stat license file for %s: %w", dependency.Path, err)
		}
		if info.Size() > maxLicenseFileSize {
			return nil, fmt.Errorf("license file for %s exceeds the %d-byte inventory bound", dependency.Path, maxLicenseFileSize)
		}
		contents, err := os.ReadFile(path)
		if err != nil {
			return nil, fmt.Errorf("read license file for %s: %w", dependency.Path, err)
		}
		relative, err := filepath.Rel(root, path)
		if err != nil {
			return nil, fmt.Errorf("make license path relative for %s: %w", dependency.Path, err)
		}
		slug := safePathSegment(dependency.Path + "@" + dependency.Version)
		destination := filepath.Join(licenseRoot, slug, relative)
		if err := os.MkdirAll(filepath.Dir(destination), 0o755); err != nil {
			return nil, fmt.Errorf("create license destination: %w", err)
		}
		if err := os.WriteFile(destination, contents, 0o644); err != nil {
			return nil, fmt.Errorf("copy license file for %s: %w", dependency.Path, err)
		}
		digest := sha256.Sum256(contents)
		result = append(result, licenseFile{
			ModulePath:  dependency.Path,
			Version:     dependency.Version,
			Relative:    filepath.ToSlash(relative),
			Destination: filepath.ToSlash(filepath.Join(defaultLicenseRoot, slug, relative)),
			Hash:        hex.EncodeToString(digest[:]),
		})
	}
	return result, nil
}

func collectGoToolchainNotices(outputRoot string) (string, []licenseFile, error) {
	command := exec.Command("go", "env", "GOROOT", "GOVERSION")
	output, err := command.Output()
	if err != nil {
		return "", nil, fmt.Errorf("read Go toolchain root and version: %w", err)
	}
	lines := strings.Split(strings.TrimSpace(string(output)), "\n")
	if len(lines) != 2 {
		return "", nil, fmt.Errorf("go env returned an invalid toolchain root or version")
	}
	goRoot := filepath.Clean(strings.TrimSpace(lines[0]))
	goVersion := strings.TrimSpace(lines[1])
	if goRoot == "." || goVersion == "" {
		return "", nil, fmt.Errorf("go env returned an invalid toolchain root or version")
	}
	toolchainOutput := filepath.Join(outputRoot, "go-toolchain")
	if err := os.RemoveAll(toolchainOutput); err != nil {
		return "", nil, fmt.Errorf("replace generated Go toolchain notice directory: %w", err)
	}
	paths := make(map[string]struct{})
	for _, name := range []string{"LICENSE", "PATENTS"} {
		path := filepath.Join(goRoot, name)
		if _, err := os.Stat(path); err == nil {
			paths[path] = struct{}{}
		} else if !errors.Is(err, os.ErrNotExist) {
			return "", nil, fmt.Errorf("inspect Go toolchain %s: %w", name, err)
		} else if name == "LICENSE" {
			return "", nil, fmt.Errorf("Go toolchain license file is missing")
		}
	}
	vendorRoot := filepath.Join(goRoot, "src", "vendor")
	if _, err := os.Stat(vendorRoot); err == nil {
		if err := filepath.WalkDir(vendorRoot, func(path string, entry os.DirEntry, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}
			if entry.Type()&os.ModeSymlink != 0 || entry.IsDir() {
				return nil
			}
			if isLicenseName(entry.Name()) {
				paths[path] = struct{}{}
			}
			return nil
		}); err != nil {
			return "", nil, fmt.Errorf("scan Go standard-library vendored notices: %w", err)
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", nil, fmt.Errorf("inspect Go standard-library vendor directory: %w", err)
	}

	ordered := make([]string, 0, len(paths))
	for path := range paths {
		ordered = append(ordered, path)
	}
	sort.Strings(ordered)
	files := make([]licenseFile, 0, len(ordered))
	for _, path := range ordered {
		info, err := os.Stat(path)
		if err != nil {
			return "", nil, fmt.Errorf("stat Go toolchain notice: %w", err)
		}
		if info.Size() > maxLicenseFileSize {
			return "", nil, fmt.Errorf("Go toolchain notice exceeds the %d-byte inventory bound", maxLicenseFileSize)
		}
		contents, err := os.ReadFile(path)
		if err != nil {
			return "", nil, fmt.Errorf("read Go toolchain notice: %w", err)
		}
		relative, err := filepath.Rel(goRoot, path)
		if err != nil {
			return "", nil, fmt.Errorf("make Go toolchain notice path relative: %w", err)
		}
		destination := filepath.Join(outputRoot, "go-toolchain", relative)
		if err := os.MkdirAll(filepath.Dir(destination), 0o755); err != nil {
			return "", nil, fmt.Errorf("create Go toolchain notice destination: %w", err)
		}
		if err := os.WriteFile(destination, contents, 0o644); err != nil {
			return "", nil, fmt.Errorf("copy Go toolchain notice: %w", err)
		}
		digest := sha256.Sum256(contents)
		files = append(files, licenseFile{
			Relative:    filepath.ToSlash(relative),
			Destination: filepath.ToSlash(filepath.Join("go-toolchain", relative)),
			Hash:        hex.EncodeToString(digest[:]),
		})
	}
	return goVersion, files, nil
}

func isLicenseName(name string) bool {
	// Some projects keep license-related source helpers beside the legal texts
	// (for example license_test.go or licenses/licenses.go). Those files are not
	// license notices and must not be copied into the redistribution bundle.
	if strings.EqualFold(filepath.Ext(name), ".go") {
		return false
	}
	upper := strings.ToUpper(name)
	for _, prefix := range []string{"LICENSE", "LICENCE", "COPYING", "COPYRIGHT", "NOTICE", "PATENTS"} {
		if strings.HasPrefix(upper, prefix) {
			return true
		}
	}
	return false
}

func safePathSegment(value string) string {
	var result strings.Builder
	for _, r := range value {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '.' || r == '-' || r == '_' {
			result.WriteRune(r)
		} else {
			result.WriteByte('_')
		}
	}
	return result.String()
}

func renderInventory(dependencies []dependency, packagePattern, tags, goos, goarch, goVersion string, goFiles []licenseFile, missing int) []byte {
	var output strings.Builder
	output.WriteString("# Third-party notices for the Tailscale broker\n\n")
	fmt.Fprintf(&output, "Generated by tools/license_inventory.go from go list dependency closure for package %s", packagePattern)
	if tags != "" {
		fmt.Fprintf(&output, " with build tags %s", tags)
	}
	if goos == "" {
		goos = "current GOOS"
	}
	if goarch == "" {
		goarch = "current GOARCH"
	}
	fmt.Fprintf(&output, ". The dependency closure uses GOOS=%s and GOARCH=%s.\n\n", goos, goarch)
	output.WriteString("This is a reproducible inventory of recognized license and notice files, not an SPDX parser or a complete licensing audit. Modules with no recognized file are marked for manual review. Corresponding verbatim source files are copied under dependency_licenses/.\n\n")
	fmt.Fprintf(&output, "Modules inventoried: %d. Modules with no recognized file: %d.\n\n", len(dependencies), missing)
	fmt.Fprintf(&output, "## Go runtime and standard-library notices\n\n")
	fmt.Fprintf(&output, "Built with %s. The Go runtime and standard-library code are linked into the broker; this bundle includes the Go distribution license, any available patent notice, and all recognized license/notice files found under GOROOT/src/vendor.\n\n", goVersion)
	for _, file := range goFiles {
		fmt.Fprintf(&output, "- %s (SHA-256 %s; bundled as %s)\n", file.Relative, file.Hash, file.Destination)
	}
	output.WriteString("\n")
	output.WriteString("## Dependency files\n\n")
	for _, dependency := range dependencies {
		fmt.Fprintf(&output, "### %s@%s\n\n", dependency.Path, dependency.Version)
		if dependency.Replacement != "" {
			fmt.Fprintf(&output, "Source replacement: %s.\n\n", dependency.Replacement)
		}
		if dependency.Path == "tailscale.com" {
			fmt.Fprintf(&output, "Upstream source: [tailscale/tailscale %s LICENSE](https://github.com/tailscale/tailscale/blob/%s/LICENSE). The pinned upstream license identifies the BSD 3-Clause terms and Tailscale Inc & contributors.\n\n", dependency.Version, dependency.Version)
		}
		if len(dependency.Files) == 0 {
			output.WriteString("No recognized license or notice file was found in the module root or its license directories. Manual review is required.\n\n")
			continue
		}
		for _, file := range dependency.Files {
			fmt.Fprintf(&output, "- %s (SHA-256 %s; bundled as %s)\n", file.Relative, file.Hash, file.Destination)
		}
		output.WriteString("\n")
	}
	return []byte(output.String())
}
