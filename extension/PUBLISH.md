# Publishing to the VS Code Marketplace

Right now the extension ships as a manually-downloaded `.vsix` from
`railcall.ai/railcall-vscode.vsix`. That works but it means no
auto-updates, no search discoverability in the VS Code Extensions
panel, no install counter, no ratings. Getting on the official
marketplace is a one-time setup + a `vsce publish` per release.

## One-time setup (10 minutes, Sami)

1. **Create the RailCall publisher account** — open
   https://marketplace.visualstudio.com/manage/createpublisher and
   sign in with the Microsoft account you want to own the publisher.
   Set the publisher id to exactly `railcall` (must match
   `package.json > "publisher"`).

2. **Create an Azure DevOps Personal Access Token** —
   https://dev.azure.com/ → sign in with the same Microsoft account →
   User Settings → Personal Access Tokens → New Token:
   - Name: `railcall vsce publish`
   - Organization: **All accessible organizations**
   - Expiration: 1 year (renew when it lapses)
   - Scopes: **Custom defined → Marketplace → Manage**
   Save the token — it's shown once. Store it in your password
   manager alongside the other publish credentials.

3. **Log the vsce CLI in on this machine** —
   ```
   cd /Users/macbook/raill/railcall-core/extension
   npx vsce login railcall
   # paste the PAT when prompted
   ```
   The token is stored under `~/.vsce`. From this point on you can
   publish without re-entering it.

## Every release (30 seconds)

```
cd /Users/macbook/raill/railcall-core/extension
npx tsc -p .
npx vsce publish
```

`vsce publish` reads the version from `package.json`, packages the
`.vsix`, uploads to the marketplace, and (about a minute later) makes
it live at
https://marketplace.visualstudio.com/items?itemName=railcall.railcall.

For a version bump combined with the publish, use `vsce publish patch`
(0.6.0 → 0.6.1) or `vsce publish minor`.

## Also mirror the local .vsix (optional but recommended)

The site's `/railcall-vscode.vsix` link should keep working as a
fallback for people who install by URL (`code --install-extension
https://...`). After `vsce publish`:

```
cp railcall-*.vsix /Users/macbook/raill/railcall-contrib/website-v2/public/railcall-vscode.vsix
cd /Users/macbook/raill/railcall-contrib
git add website-v2/public/railcall-vscode.vsix
git commit -m "mirror railcall-vscode <version>"
git push
ssh -i ~/.ssh/id_ed255199 sami@157.230.177.45 "cd ~/railcall-contrib/website-v2 && git pull -q && npm run build && pm2 restart railcall-website"
```

## Currently packaged

- **Version**: 0.6.0 (governance HUD, chat webview removed)
- **Publisher**: `railcall` (matches expected marketplace publisher id)
- **Category**: Other, Testing
- **License**: MIT
- **Size**: ~30 KB
