#!/bin/bash

# This is used in pacakge.json to block the help pages from public access, and copy the assets to the correct directory

AUTH_CONTENT="import frappe
from frappe import _

if frappe.session.user=='Guest':
    frappe.throw(_(\"You need to be logged in to access this page\"), frappe.PermissionError)"

for file in posnext/www/posnext_*.html; do
  if [ -f "$file" ]; then
    py_file="posnext/www/$(basename "$file" .html).py"
    echo "$AUTH_CONTENT" > "$py_file"
  fi
done

rm -rf ./posnext/public/chunks
mv ./posnext/www/assets/posnext/chunks ./posnext/public/.
mv ./posnext/www/assets/posnext/*.js ./posnext/public/.
mv ./posnext/www/assets/posnext/*.css ./posnext/public/.