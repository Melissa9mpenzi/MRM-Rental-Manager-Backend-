# Put RentDirect on **your** GitHub (not only Melissa’s)

## Why you don’t see it on your profile

`git push` sends code to whatever URL is in `origin`. Right now all three projects use:

- `https://github.com/Melissa9mpenzi/MRM-Rental-Manager-Backend-.git`
- `https://github.com/Melissa9mpenzi/MRM-Rental-Manager-Frontend-.git`
- `https://github.com/Melissa9mpenzi/MRM-Rental-Manager-Mobile-.git`

Your commits **are** on GitHub (branch `feature-fix` / `main`), but they live under **Melissa’s** account. They will not appear on your profile until you push to **your** repos or are added as a collaborator.

Your commits are already authored as **Nakungu Esther** (`nakunguesther044@gmail.com`) — that part is correct.

---

## Option A — Your own copies (recommended)

### 1. On GitHub (logged in as **you**)

Create **three empty** repositories (no README, no .gitignore). Use these links while signed in as **nakungu-esther**:

| Repo | Create link |
|------|-------------|
| Backend | https://github.com/new?name=MRM-Rental-Manager-Backend- |
| Frontend | https://github.com/new?name=MRM-Rental-Manager-Frontend- |
| Mobile | https://github.com/new?name=MRM-Rental-Manager-Mobile- |

Leave them **empty** (uncheck “Add a README”).

Your GitHub username: **[nakungu-esther](https://github.com/nakungu-esther)**

### 2. On your PC (PowerShell)

From the backend folder, set your username and run the script (copy the script to each repo or run paths below):

```powershell
$env:GITHUB_USER = "nakungu-esther"

cd D:\MRM-Rental-Manager-Backend-
.\scripts\push-to-my-github.ps1

cd D:\MRM-Rental-Manager-Frontend-
.\scripts\push-to-my-github.ps1

cd D:\MRM-Rental-Manager-Mobile-
.\scripts\push-to-my-github.ps1
```

That adds remote `mygithub` and pushes your current branches. Melissa’s `origin` is unchanged.

### 3. Verify

Open `https://github.com/YourUsername/MRM-Rental-Manager-Backend-` — you should see branch `feature-fix`.

---

## Option B — Collaborator on Melissa’s repos

Ask Melissa to add **nakunguesther044@gmail.com** as **Admin** or **Write** on each repo:

**Settings → Collaborators → Add people**

You can push to the same URLs; the repo still “belongs” to her unless she transfers ownership.

---

## Option C — Transfer ownership

Melissa can transfer each repo to you:

**Settings → General → Danger zone → Transfer ownership**

Only do this if you both agree.

---

## Push to BOTH with one command (recommended)

Run once per project folder:

```powershell
.\scripts\setup-push-both.ps1
```

After that, a normal **`git push`** updates **Melissa’s repo and yours** at the same time.

Check it worked:

```powershell
git remote show origin
```

You should see **two** `Push URL` lines (Melissa + nakungu-esther).

---

## Git identity (already set on your machine)

Commits should use your email so GitHub links them to you:

```powershell
git config --global user.name "Nakungu Esther"
git config --global user.email "nakunguesther044@gmail.com"
```

Use the **same email** on your GitHub account: **Settings → Emails**.
