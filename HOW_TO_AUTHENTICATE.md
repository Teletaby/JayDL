# 🔐 How to Authenticate with Shared Gmail Account

Now that the **"Authenticate"** button is added to the app, here's exactly how to use it:

## ✅ Steps to Set Up Shared Account

### Step 1: Open Your App
Go to `http://localhost:8000` in your browser

### Step 2: Look for the Yellow Tip Box
You should see a yellow box at the top that says:
```
🎬 YouTube Download Tip
For YouTube downloads to work, make sure you are signed into YouTube in your browser...
```

### Step 3: Click the "Authenticate" Button
In that yellow box, you'll now see a **blue button** that says:
```
🔵 Authenticate
```
Click it!

### Step 4: Google Login Popup Opens
A new popup window will appear with the Google login screen.

### Step 5: Sign In with the Shared Email
Enter these credentials:
- **Email:** `testacc123ud@gmail.com`
- **Password:** [your password for this account]

### Step 6: Grant Permissions
Google will ask permission to access YouTube. Click **"Allow"** or **"Continue"**.

### Step 7: See Success Message
After permissions are granted, you'll see a popup message:
```
✅ YouTube authentication successful! You can now download YouTube videos.
```

---

## 📝 After Success - Save as Shared Account

Now you need to **save these credentials as the shared account**. 

### Open Browser Developer Tools
Press **F12** on your keyboard to open Developer Tools.

### Go to Console Tab
Click the **"Console"** tab at the top.

### Paste This Code
Copy and paste this into the console:

```javascript
fetch('http://localhost:5000/api/oauth2/setup-shared-account', {
    method: 'GET',
    credentials: 'include'
})
.then(r => r.json())
.then(d => {
    console.log('Setup Result:', d);
    if (d.success) {
        alert('✅ Shared account saved successfully!');
    } else {
        alert('❌ Setup failed: ' + d.error);
    }
});
```

### Press Enter
You should see output like:
```
Setup Result: {
  success: true,
  message: "Shared account setup successful for testacc123ud",
  account_info: {
    channel_name: "testacc123ud",
    setup_timestamp: "2025-12-05T..."
  }
}
```

---

## ✅ Verify It Worked

Paste this code into the console to verify:

```javascript
fetch('http://localhost:5000/api/oauth2/shared-account-status')
.then(r => r.json())
.then(d => {
    console.log('Status:', d);
    if (d.has_shared_account && d.account_info.is_valid) {
        alert('✅ Shared account is active and valid!');
    }
});
```

You should see:
```
✅ Shared account is active and valid!
```

---

## 🎉 Done!

Once you see the success message, **all users can download YouTube videos without authentication!**

---

## 📱 What You'll See

### Before Setup
```
🎬 YouTube Download Tip
For YouTube downloads to work, make sure you are signed into YouTube...

[🔵 Authenticate] [❓ Help] [✕ Dismiss]
```

### After Clicking Authenticate
- Google login popup appears
- Enter testacc123ud@gmail.com
- Grant permissions
- Success message appears

### After Running Setup Command
- Console shows: `success: true`
- You see: ✅ Shared account saved!

### Final Status
- Shared account is active
- All users can download freely
- No more authentication needed!

---

## 🆘 Troubleshooting

**Q: I don't see the yellow box with the button?**
A: Try refreshing the page. If it still doesn't show, the page might be loading the old version. Clear your cache (Ctrl+Shift+Delete) and refresh.

**Q: The popup is blocked?**
A: Your browser is blocking popups. Allow popups for localhost:8000 in your browser settings.

**Q: Console says "error"?**
A: Make sure you waited for the success message before running the setup command. The session might have expired if you waited too long.

**Q: Status says "is_valid: false"?**
A: The credentials expired. Go through the authentication process again.

---

## 💡 Quick Summary

```
1. Open app → See yellow box
2. Click "Authenticate" button
3. Sign in: testacc123ud@gmail.com
4. Grant permissions
5. See success message
6. Open console (F12)
7. Paste setup command
8. See success response
9. Verify with status command
10. ✅ Done! All users can download freely
```

---

**You're ready to go! 🚀**
