from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, Ad, Category, User, favorites  # ← добавим favorites
from config import Config
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import requests
from math import radians, sin, cos, sqrt, atan2

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = 'super_secret_key_123'

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

CATEGORIES = [
    "Выпечка и кондитерские изделия",
    "Овощи, фрукты и зелень",
    "Домашние заготовки и консервы",
    "Мёд и продукты пчеловодства",
    "Молочные продукты",
    "Мясо, рыба и продукты из них",
    "Напитки",
    "Семена, саженцы и сопутствующее",
    "Другое съедобное"
]

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def geocode_city(city):
    try:
        query_city = f"{city}, Оренбургская область, Россия"
        url = f"https://nominatim.openstreetmap.org/search?q={query_city}&format=json&limit=1"
        headers = {'User-Agent': 'foodboard/1.0 (твой_реальный_email@mail.ru)'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.ok and response.json():
            data = response.json()[0]
            return float(data['lat']), float(data['lon'])
        else:
            return None, None
    except:
        return None, None

with app.app_context():
    db.create_all()
    if Category.query.count() == 0:
        for cat_name in CATEGORIES:
            db.session.add(Category(name=cat_name))
        db.session.commit()

@app.route('/')
def index():
    user_lat = request.args.get('lat', type=float)
    user_lon = request.args.get('lon', type=float)
    near_city = request.args.get('near_city')
    search_query = request.args.get('q')

    if near_city:
        user_lat, user_lon = geocode_city(near_city)
        if user_lat is None:
            flash(f'Город "{near_city}" не найден — показываем все')
            near_city = None

    nearby_mode = bool(user_lat and user_lon)
    current_city = near_city if near_city else None
    radius = 400

    ads_query = Ad.query.order_by(Ad.created_at.desc())

    if search_query:
        words = search_query.strip().split()
        for word in words:
            pattern = f"%{word}%"
            ads_query = ads_query.filter(
                (Ad.title.ilike(pattern)) | (Ad.description.ilike(pattern))
            )

    all_ads = ads_query.all()

    if nearby_mode:
        ads = []
        for ad in all_ads:
            if ad.seller.latitude and ad.seller.longitude:
                distance = haversine(user_lat, user_lon, ad.seller.latitude, ad.seller.longitude)
                ad.distance = round(distance)
                if distance <= radius:
                    ads.append(ad)
        if not ads:
            flash(f'В радиусе {radius} км ничего не найдено')
    else:
        ads = all_ads

    categories = Category.query.all()
    return render_template('index.html', ads=ads, categories=categories, nearby_mode=nearby_mode,
                           current_city=current_city, search_query=search_query or '')

@app.route('/category/<int:cat_id>')
def category(cat_id):
    category = Category.query.get_or_404(cat_id)
    ads = Ad.query.filter_by(category_id=cat_id).order_by(Ad.created_at.desc()).all()
    categories = Category.query.all()
    return render_template('category.html', category=category, ads=ads, categories=categories)

@app.route('/ad/<int:ad_id>')
def ad_detail(ad_id):
    ad = Ad.query.get_or_404(ad_id)
    categories = Category.query.all()
    is_favorite = current_user.is_authenticated and ad in current_user.favorites
    return render_template('ad_detail.html', ad=ad, categories=categories, is_favorite=is_favorite)

@app.route('/profile')
@login_required
def profile():
    my_ads = Ad.query.filter_by(user_id=current_user.id).order_by(Ad.created_at.desc()).all()
    favorite_ads = current_user.favorites
    categories = Category.query.all()
    return render_template('profile.html', my_ads=my_ads, favorite_ads=favorite_ads, categories=categories)

@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        current_user.name = request.form['name']
        current_user.phone = request.form['phone']
        city = request.form['city']
        current_user.city = city
        lat, lon = geocode_city(city)
        current_user.latitude = lat
        current_user.longitude = lon
        db.session.commit()
        flash('Профиль обновлён!' + (' Координаты обновлены' if lat else ' Город не найден'))
        return redirect(url_for('profile'))

    categories = Category.query.all()
    return render_template('edit_profile.html', categories=categories)

@app.route('/edit_ad/<int:ad_id>', methods=['GET', 'POST'])
@login_required
def edit_ad(ad_id):
    ad = Ad.query.get_or_404(ad_id)
    if ad.user_id != current_user.id:
        flash('Это не ваше объявление!')
        return redirect(url_for('profile'))

    categories = Category.query.all()

    if request.method == 'POST':
        ad.title = request.form['title']
        ad.description = request.form['description']
        ad.price = float(request.form['price'])
        ad.category_id = int(request.form['category'])

        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                ad.image = filename

        db.session.commit()
        flash('Объявление обновлено!')
        return redirect(url_for('profile'))

    return render_template('edit_ad.html', ad=ad, categories=categories)

@app.route('/delete_ad/<int:ad_id>', methods=['POST'])
@login_required
def delete_ad(ad_id):
    ad = Ad.query.get_or_404(ad_id)
    if ad.user_id != current_user.id:
        flash('Это не ваше объявление!')
        return redirect(url_for('profile'))

    db.session.delete(ad)
    db.session.commit()
    flash('Объявление удалено')
    return redirect(url_for('profile'))

@app.route('/toggle_favorite/<int:ad_id>', methods=['POST'])
@login_required
def toggle_favorite(ad_id):
    ad = Ad.query.get_or_404(ad_id)
    if ad.user_id == current_user.id:
        flash('Своё объявление нельзя добавить в избранное')
        return redirect(request.referrer or url_for('index'))

    if ad in current_user.favorites:
        current_user.favorites.remove(ad)
        flash('Убрано из избранного')
    else:
        current_user.favorites.append(ad)
        flash('Добавлено в избранное')

    db.session.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        phone = request.form['phone']
        city = request.form['city']

        if User.query.filter_by(email=email).first():
            flash('Этот email уже занят')
            return redirect(url_for('register'))

        lat, lon = geocode_city(city)

        new_user = User(
            email=email,
            password=generate_password_hash(password),
            name=name,
            phone=phone,
            city=city,
            latitude=lat,
            longitude=lon
        )
        db.session.add(new_user)
        db.session.commit()
        flash('Регистрация прошла! ' + ('Координаты найдены' if lat else 'Город не найден'))
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Неправильный email или пароль')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_ad():
    categories = Category.query.all()
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        price = float(request.form['price'])
        category_id = int(request.form['category'])

        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_filename = filename

        new_ad = Ad(
            title=title,
            description=description,
            price=price,
            image=image_filename,
            category_id=category_id,
            user_id=current_user.id
        )
        db.session.add(new_ad)
        db.session.commit()
        flash('Объявление добавлено!')
        return redirect(url_for('index'))

    return render_template('add_ad.html', categories=categories)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
