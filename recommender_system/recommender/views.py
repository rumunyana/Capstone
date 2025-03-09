from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseRedirect
from django.urls import reverse
from .models import StudentProfile, Prediction, Testimonial, Feedback, ContactMessage, TeacherProfile, RecommendationOverride
import joblib
import numpy as np
import random
import pandas as pd
import os
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.db.models import Count, F
from django.contrib.auth.models import User

#BASE_DIR
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#path to the saved models folder
MODEL_PATH = os.path.join(BASE_DIR, "recommender", "saved_models")

#Try/except block for model loading to handle errors
try:
    rf_classifier = joblib.load(os.path.join(MODEL_PATH, "random_forest_model.pkl"))
    knn_model = joblib.load(os.path.join(MODEL_PATH, "knn_recommender_model.pkl"))
    similarity_matrix = joblib.load(os.path.join(MODEL_PATH, "similarity_matrix.pkl"))
    label_mappings = joblib.load(os.path.join(MODEL_PATH, "label_mappings.pkl"))
    csv_file_path = os.path.join(MODEL_PATH, 'rwanda_students_final_v3.csv')
    
    df = pd.read_csv(csv_file_path)
    
    # Define categorical columns and target variable
    categorical_cols = ["gender", "school_type", "location", "parental_education_level",
                        "internet_access", "parental_career", "extracurricular_activity", 
                        'interest', 'recommended_stream']
    features = df.drop(columns=["student_id", "recommended_stream"])
    target = df["recommended_stream"]
    
    MODELS_LOADED = True
except Exception as e:
    print(f"Error loading models: {e}")
    MODELS_LOADED = False

def landing(request):
    """Landing page view"""
    return render(request, 'landing.html')

def student_signin(request):
    """Handle user registration"""
    if request.method == 'POST':
        full_name = request.POST.get('full_name')
        school = request.POST.get('school')
        email = request.POST.get('email')

        #check if email already exists
        student = StudentProfile.objects.filter(email=email).first()
        if student:
            request.session['student_id'] = student.id
            return redirect('home')  #redirect directly to home
        
        #create new student profile
        student = StudentProfile.objects.create(full_name=full_name, school=school, email=email)
        request.session['student_id'] = student.id  # Log in new user

        return redirect('home')
    return render(request, 'register.html')


def teacher_signin(request):
    if request.method == "POST":
        full_name = request.POST.get("full_name")
        school_name = request.POST.get("school")
        email = request.POST.get("email")
        subject_specialization = request.POST.get("subject_specialization")

        # Check if email is already registered
        teacher, created = TeacherProfile.objects.get_or_create(
            email=email,
            defaults={
                "full_name": full_name,
                "school_name": school_name,
                "subject_specialization": subject_specialization,
            },
        )

        # Store teacher's email in session
        request.session["teacher_email"] = teacher.email

        return redirect("teacher_dashboard")  # Redirect to dashboard

    return render(request, "register_teacher.html")

#homepage view function
def home(request):
    # Check if user is logged in
    student_id = request.session.get('student_id')
    if not student_id:
        return redirect('landing')
    
    try:
        user = StudentProfile.objects.get(id=student_id)
    except StudentProfile.DoesNotExist:
        # Invalid session, redirect to landing
        del request.session['student_id']
        return redirect('landing')
    
    testimonials = Testimonial.objects.order_by('-created_at')[:6] #display testimonials
    
    print("Testimonials found:", testimonials)
    print("Testimonials count:", testimonials.count())
    for testi in testimonials:
        print(f"Testimonial: {testi.name}, Rating: {testi.rating}, Content: {testi.content}")
    
    #check if user has a prediction and testimonial
    user_has_prediction = Prediction.objects.filter(student=user).exists()
    user_has_testimonial = Testimonial.objects.filter(student=user).exists()
    
    context = {
        'user': user,
        'testimonials': testimonials,
        'user_has_prediction': user_has_prediction,
        'user_has_testimonial': user_has_testimonial
    }
    
    return render(request, 'home.html', context)

# hybrid Recommendation Function
def hybrid_recommend(student_input):
    student_df = pd.DataFrame([student_input])
    #ensure all feature columns are present
    missing_cols = [col for col in features.columns if col not in student_df.columns]
    for col in missing_cols:
        student_df[col] = 0
    student_df = student_df[features.columns] #to match training order

    predicted_stream = rf_classifier.predict(student_df)[0]    #predict stream using Random Forest (content-based filtering)

    distances, similar_student_indices = knn_model.kneighbors(student_df, n_neighbors=5)     #find the closest matches using k-NN (collaborative filtering)
    collaborative_recs = target.iloc[similar_student_indices[0][1:]].tolist()  #ignore first one (itself)

    final_recommendations = list(dict.fromkeys([predicted_stream] + collaborative_recs)) #remove duplicates while keeping order
    all_possible_streams = target.unique().tolist()  #at least 3 recommendations
    
    all_possible_streams = [s for s in all_possible_streams if isinstance(s, (int, float, np.integer, np.floating))]    #remove non-numeric values

    additional_recs = [s for s in all_possible_streams if s not in final_recommendations]
    random.shuffle(additional_recs)
    
    while len(final_recommendations) < 3 and additional_recs:  #adding a subject untill its up to 3 unique recommendations
        final_recommendations.append(additional_recs.pop())

    return predicted_stream, final_recommendations

#predict_student function
def predict_student(request):
    context = {}
    if not MODELS_LOADED:
        context["error_message"] = "System is currently unavailable. Please try again later." #confirms if models are loaded
        return render(request, "predict.html", context)

    #step 1: Initial form submission from home page
    if request.method == "POST" and "name" in request.POST and "school" in request.POST and "age" not in request.POST:
        name = request.POST.get("name", "").strip()
        school = request.POST.get("school", "").strip()

        if not name or not school:
            return redirect("home")

        context["name"] = name
        context["school"] = school

        request.session["student_name"] = name
        request.session["school_name"] = school

        return render(request, "predict.html", context)

    #step 2: Detailed student form submission
    elif request.method == "POST" and "age" in request.POST:
        name = request.session.get("student_name", request.POST.get("name", "Student"))
        school = request.session.get("school_name", request.POST.get("school", ""))
        context["name"] = name
        context["school"] = school

        required_fields = [
            "age", "math_score", "english_score", "science_score", 
            "history_score", "attendance_rate", "study_hours_per_week", 
            "household_income", "gender", "school_type", "location", 
            "parental_education_level", "internet_access", "parental_career", 
            "extracurricular_activity", "interest"
        ]

        #check for missing fields
        missing_fields = [field for field in required_fields if field not in request.POST or not request.POST[field]]
        if missing_fields:
            context["error_message"] = f"Please fill out all required fields. Missing: {', '.join(missing_fields)}"
            return render(request, "predict.html", context)

        try:
            student_input = {}

            #validate numerical fields
            numerical_fields = [
                "age", "math_score", "english_score", "science_score", 
                "history_score", "attendance_rate", "study_hours_per_week", 
                "household_income"
            ]

            for field in numerical_fields:
                value = int(request.POST[field])
                
                if field in ["math_score", "english_score", "science_score", "history_score"] and not (0 <= value <= 100):
                    raise ValueError(f"{field.replace('_', ' ').title()} must be between 0 and 100")
                elif field == "attendance_rate" and not (0 <= value <= 100):
                    raise ValueError("Attendance rate must be between 0 and 100")
                elif field == "age" and not (10 <= value <= 25):
                    raise ValueError("Age must be between 10 and 25")

                student_input[field] = value

            #categorical fields
            categorical_fields = [
                "gender", "school_type", "location", "parental_education_level", 
                "internet_access", "parental_career", "extracurricular_activity", "interest"
            ]

            for field in categorical_fields:
                student_input[field] = int(request.POST[field])

            predicted_code, recommendations = hybrid_recommend(student_input) #predict subject and recommendations
            
            #label mappings
            label_mappings = {
                0: "Arts",
                1: "Business",
                2: "Healthcare",
                3: "Humanities",
                4: "STEM"
            }

            #prediction is properly mapped from integer to string
            predicted_subject = label_mappings.get(predicted_code, f"Unknown ({predicted_code})")
            
            #recommendations are properly mapped and unique
            decoded_recommendations = []
            for rec in recommendations:
                #convert any numpy type to int before checking the mapping
                rec_code = int(rec) if isinstance(rec, (np.int32, np.int64)) else rec
                
                if isinstance(rec_code, int):
                    decoded_recommendations.append(label_mappings.get(rec_code, f"Unknown ({rec_code})"))
                else:
                    decoded_recommendations.append(rec)

            decoded_recommendations = list(dict.fromkeys(decoded_recommendations)) #remove duplicates while maintaining order
            
            #remove the predicted subject from recommendations if it exists
            if predicted_subject in decoded_recommendations:
                decoded_recommendations.remove(predicted_subject)
            
            #to confirm 3 recommendations
            all_subjects = [label_mappings[i] for i in range(5)]
            available_subjects = [subject for subject in all_subjects if subject != predicted_subject and subject not in decoded_recommendations]
            
            #if not up to 3, add the next in line
            while len(decoded_recommendations) < 3 and available_subjects:
                next_subject = available_subjects.pop(0)
                decoded_recommendations.append(next_subject)
            
            recommended_subjects = decoded_recommendations[:3] #top 3

            student_id = request.session.get('student_id') #check if user is logged in
            if student_id:
                try:
                    student = StudentProfile.objects.get(id=student_id)
                    
                    #create and save prediction with the integer code
                    #store the original predicted code for database consistency
                    prediction = Prediction.objects.create(
                        student=student,
                        predicted_subject=predicted_code,
                        recommended_subjects=",".join(recommended_subjects)
                    )

                    if not student.age:  #only update if fields are empty
                        student.age = student_input["age"]
                        student.math_score = student_input["math_score"]
                        student.english_score = student_input["english_score"]
                        student.science_score = student_input["science_score"]
                        student.history_score = student_input["history_score"]
                        student.attendance_rate = student_input["attendance_rate"]
                        student.study_hours_per_week = student_input["study_hours_per_week"]
                        student.household_income = student_input["household_income"]
                        student.gender = student_input["gender"]
                        student.school_type = student_input["school_type"]
                        student.location = student_input["location"]
                        student.parental_education_level = student_input["parental_education_level"]
                        student.internet_access = student_input["internet_access"]
                        student.parental_career = student_input["parental_career"]
                        student.extracurricular_activity = student_input["extracurricular_activity"]
                        student.interest = student_input["interest"]
                        student.save()
                    
                    return redirect('result', prediction_id=prediction.id) #redirect to results page with prediction ID
                    
                except StudentProfile.DoesNotExist:
                    #to store prediction data in session for non-logged in users or failed lookup
                    request.session['temp_prediction'] = {
                        'predicted_subject': predicted_subject,  # Store the string representation
                        'recommended_subjects': recommended_subjects,
                        'student_input': student_input
                    }
                    return redirect('result')
            else:
                #store prediction data in session for non-logged in users
                request.session['temp_prediction'] = {
                    'predicted_subject': predicted_subject,  # Store the string representation
                    'recommended_subjects': recommended_subjects,
                    'student_input': student_input
                }
                return redirect('result')

        except ValueError as e:
            context["error_message"] = str(e)
        except KeyError as e:
            context["error_message"] = f"Missing field: {e}. Please fill out all fields."
        except Exception as e:
            import traceback
            traceback.print_exc()
            context["error_message"] = f"An error occurred: {str(e)}"

    #step 3: Handle GET request
    else:
        context["name"] = request.session.get("student_name", "")
        context["school"] = request.session.get("school_name", "")

    return render(request, "predict.html", context)


#result_view function
def result_view(request, prediction_id=None):
    context = {}
    
    #label mappings for converting integer codes to string representations
    label_mappings = {
        0: "Arts",
        1: "Business",
        2: "Healthcare",
        3: "Humanities",
        4: "STEM"
    }
    
    #check if user is logged in
    student_id = request.session.get('student_id')
    if student_id:
        try:
            user = StudentProfile.objects.get(id=student_id)
            context['user'] = user
            
            if prediction_id: #check if user have a prediction ID
                try:
                    prediction = Prediction.objects.get(id=prediction_id, student=user)
                    context['prediction'] = prediction
                    context['prediction_found'] = True
                    
                    #map the integer predicted_subject to its string representation
                    predicted_subject = label_mappings.get(prediction.predicted_subject, 
                                                        f"Unknown ({prediction.predicted_subject})")
                    context['predicted_subject'] = predicted_subject
                    
                    #then convert comma-separated string back to list
                    recommended_subjects = prediction.recommended_subjects.split(',')
                    context['recommended_subjects'] = recommended_subjects
                    
                    #confirm if user has already submitted a testimonial for this prediction
                    user_testimonial = Testimonial.objects.filter(student=user, prediction=prediction).first()
                    context['has_testimonial'] = user_testimonial is not None
                    context['user_testimonial'] = user_testimonial
                    
                except Prediction.DoesNotExist:
                    context['error_message'] = "The requested prediction was not found or doesn't belong to you."
            else:
                # Get latest prediction for this user if no specific ID
                prediction = Prediction.objects.filter(student=user).order_by('-created_at').first()
                if prediction:
                    context['prediction'] = prediction
                    context['prediction_found'] = True
                    
                    #map the integer predicted_subject to its string representation
                    predicted_subject = label_mappings.get(prediction.predicted_subject, 
                                                        f"Unknown ({prediction.predicted_subject})")
                    context['predicted_subject'] = predicted_subject
                    
                    #convert comma-separated string back to list
                    recommended_subjects = prediction.recommended_subjects.split(',')
                    context['recommended_subjects'] = recommended_subjects
                    
                    #check if user has already submitted a testimonial for this prediction
                    user_testimonial = Testimonial.objects.filter(student=user, prediction=prediction).first()
                    context['has_testimonial'] = user_testimonial is not None
                    context['user_testimonial'] = user_testimonial
                else:
                    temp_prediction = request.session.pop('temp_prediction', None) #check for temporary prediction data in session
                    if temp_prediction:
                        predicted_subject = temp_prediction['predicted_subject']
                        context['predicted_subject'] = predicted_subject
                        
                        recommended_subjects = temp_prediction['recommended_subjects']
                        context['recommended_subjects'] = recommended_subjects
                        context['student_input'] = temp_prediction['student_input']
                        context['is_temporary'] = True
                    else:
                        context['error_message'] = "No predictions found for your account. Try making a prediction first."
            
        except StudentProfile.DoesNotExist:
            del request.session['student_id'] #invalid session, redirect to landing
            return redirect('landing')
    else:
        temp_prediction = request.session.pop('temp_prediction', None) #if not logged in, check for temporary prediction data
        if temp_prediction:
            predicted_subject = temp_prediction['predicted_subject']
            context['predicted_subject'] = predicted_subject
        
            recommended_subjects = temp_prediction['recommended_subjects']
            context['recommended_subjects'] = recommended_subjects
            context['student_input'] = temp_prediction['student_input']
            context['is_temporary'] = True
        else:
            return redirect('landing') #if no prediction data and not logged in
    
    return render(request, 'results.html', context)

#handling testimonial submission
def add_testimonial_view(request):
    if request.method == 'POST':
        student_id = request.session.get('student_id')
        if not student_id:
            return redirect('landing')

        try:
            user = StudentProfile.objects.get(id=student_id)
        except StudentProfile.DoesNotExist:
            del request.session['student_id']
            return redirect('landing')

        content = request.POST.get('content')
        rating = request.POST.get('rating')
        prediction_id = request.POST.get('prediction_id')

        try:
            prediction = Prediction.objects.get(id=prediction_id, student=user)

            if Testimonial.objects.filter(student=user, prediction=prediction).exists():
                messages.error(request, "You have already submitted feedback for this prediction.")
                return redirect('home')

            Testimonial.objects.create(student=user, prediction=prediction, name=user.full_name, content=content, rating=rating)


        except Prediction.DoesNotExist:
            messages.error(request, "The specified prediction was not found.")

    return redirect('home')

#about page function
def about(request):
    return render(request, 'about.html')

#contact page to handle form submission
def contact_view(request):
    student_id = request.session.get('student_id')
    context = {}
    
    if student_id:
        try:
            student = StudentProfile.objects.get(id=student_id)
            context['user'] = student
        except StudentProfile.DoesNotExist:
            if 'student_id' in request.session: #clear invalid session
                del request.session['student_id']
    
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        message = request.POST.get('message')

        ContactMessage.objects.create(name=name, email=email, message=message)
        
        messages.success(request, "Your message has been sent successfully!")
        return redirect('contact')

    return render(request, 'contact.html', context)

def student_guide_view(request):
    # """Render the Student Guide page with dynamic content"""
    # Get user info if logged in (optional)
    # student_id = request.session.get('student_id')
    # context = {'guide_entries': StudentGuide.objects.all().order_by('-created_at')}
    
    # if student_id:
    #     try:
    #         student = StudentProfile.objects.get(id=student_id)
    #         context['user'] = student
    #     except StudentProfile.DoesNotExist:
    #         # Clear invalid session
    #         if 'student_id' in request.session:
    #             del request.session['student_id']
    
    return render(request, 'guide.html')

#reports page function
def visuals(request):
    img_folder = os.path.join('static', 'img') #path to the folder where images are stored
    images = [
        'class_distribution.png',
        'pairplot_scores.png',
        'attendance_distribution.png',
        'violin_math_scores.png',
        'histogram_scores.png',
        'correlation_heatmap.png'
    ]
    image_paths = [os.path.join(img_folder, img) for img in images] #construct full paths for each image
    
    return render(request, 'visuals.html', {'image_paths': image_paths})


def teacher_dashboard(request):
    # Ensure the teacher is logged in via session
    if "teacher_email" not in request.session:
        return redirect("teacher_signin")

    teacher_email = request.session["teacher_email"]
    teacher = get_object_or_404(TeacherProfile, email=teacher_email)

    # Fetch all student predictions without duplicates
    # Option 1: Get the latest prediction for each student
    student_ids = StudentProfile.objects.values_list('id', flat=True)
    predictions = []
    
    for student_id in student_ids:
        # Get the latest prediction for this student
        latest_prediction = Prediction.objects.filter(
            student_id=student_id
        ).order_by('-id').first()  # Assuming higher id means more recent
        
        if latest_prediction:
            predictions.append(latest_prediction)

    # Fetch override history by this teacher
    override_history = RecommendationOverride.objects.filter(teacher=teacher).order_by('-timestamp')

    # Count total students
    total_students = StudentProfile.objects.count()

    # Count accepted recommendations - make sure this logic matches your use case
    # Assuming a recommendation is "accepted" when it hasn't been overridden
    overridden_students = RecommendationOverride.objects.values_list('student__id', flat=True).distinct()
    non_overridden = total_students - len(overridden_students)
    
    # Calculate acceptance percentage
    accepted_percentage = (non_overridden / total_students) * 100 if total_students > 0 else 0

    # Most popular stream
    stream_mapping = {
        0: "Arts",
        1: "Business",
        2: "Healthcare",
        3: "Humanities",
        4: "STEM",
    }
    
    popular_subject_counts = {}
    for prediction in predictions:
        subject = prediction.predicted_subject
        if subject in popular_subject_counts:
            popular_subject_counts[subject] += 1
        else:
            popular_subject_counts[subject] = 1
    
    popular_subject = None
    max_count = 0
    for subject, count in popular_subject_counts.items():
        if count > max_count:
            max_count = count
            popular_subject = subject
    
    popular_stream = stream_mapping.get(popular_subject, "N/A") if popular_subject is not None else "N/A"

    # Fetch only students who have predictions for the feedback dropdown
    students_with_predictions = StudentProfile.objects.filter(
        id__in=Prediction.objects.values_list('student', flat=True)
    ).distinct()
    
    # Keep track of how many students have no predictions
    all_students_count = total_students  # We already have this count
    students_with_predictions_count = students_with_predictions.count()

    context = {
        "teacher": teacher,
        "predictions": predictions,
        "override_history": override_history,
        "total_students": total_students,
        "accepted_percentage": round(accepted_percentage, 1),  # Round to 1 decimal place
        "popular_stream": popular_stream,
        "students": students_with_predictions,  # Only pass students with predictions
        "all_students_count": all_students_count,
        "students_with_predictions_count": students_with_predictions_count,
    }
    return render(request, "teacher_dashboard.html", context)

def override_recommendation(request, prediction_id):
    if "teacher_email" not in request.session:
        return redirect("teacher_signin")
    
    if request.method != "POST":
        return redirect("teacher_dashboard")
    
    # Get the prediction and teacher
    prediction = get_object_or_404(Prediction, id=prediction_id)
    teacher = get_object_or_404(TeacherProfile, email=request.session["teacher_email"])
    
    # Get form data
    new_recommendation = request.POST.get("new_recommendation")
    reason = request.POST.get("reason", "")
    
    # Validate new recommendation
    if not new_recommendation:
        messages.error(request, "Please select a new recommendation")
        return redirect("teacher_dashboard")
    
    # Convert to integer
    new_recommendation = int(new_recommendation)
    
    # Create override record
    RecommendationOverride.objects.create(
        teacher=teacher,
        student=prediction.student,
        old_recommendation=prediction.predicted_subject,
        new_recommendation=new_recommendation,
        reason=reason
    )
    
    # Update the prediction
    prediction.predicted_subject = new_recommendation
    prediction.save()
    
    # Add a success message if you have django.contrib.messages installed
    from django.contrib import messages
    messages.success(request, f"Recommendation for {prediction.student.full_name} has been updated")
    
    return redirect("teacher_dashboard")




def override_recommendation(request, prediction_id):
    if "teacher_email" not in request.session:
        return redirect("teacher_signin")  # Redirect if not logged in

    teacher_email = request.session["teacher_email"]
    teacher = get_object_or_404(TeacherProfile, email=teacher_email)  # Fetch teacher from session

    prediction = get_object_or_404(Prediction, id=prediction_id)

    if request.method == "POST":
        new_recommendation = request.POST.get("new_recommendation")

        try:
            new_recommendation = int(new_recommendation)
            if new_recommendation not in [0, 1, 2, 3, 4]:
                raise ValueError
        except ValueError:
            messages.error(request, "Invalid recommendation choice.")
            return redirect("teacher_dashboard")

        # Save override history
        RecommendationOverride.objects.create(
            teacher=teacher,
            student=prediction.student,
            old_recommendation=prediction.predicted_subject,
            new_recommendation=new_recommendation,
        )

        # Update main recommendation
        prediction.predicted_subject = new_recommendation
        prediction.save()

        messages.success(request, "Recommendation successfully overridden.")

    return redirect("teacher_dashboard")




def submit_feedback(request):
    # Ensure only logged-in teachers can submit feedback
    if "teacher_email" not in request.session:
        return redirect("teacher_signin")

    if request.method == "POST":
        student_id = request.POST.get("student_id")
        feedback_text = request.POST.get("feedback")
        rating = request.POST.get("rating", 5)
        
        # Ensure student exists
        student = get_object_or_404(StudentProfile, id=student_id)

        # Check if the student has any predictions
        prediction = Prediction.objects.filter(student=student).order_by('-id').first()
        
        # If no prediction exists, redirect with an error message
        if not prediction:
            # Use HttpResponseRedirect with the full URL including query parameters
            return HttpResponseRedirect(reverse('teacher_dashboard') + '?feedback_error=true&message=This%20student%20has%20not%20made%20any%20predictions%20yet')
            
        # Get teacher details
        teacher_email = request.session["teacher_email"]
        teacher = get_object_or_404(TeacherProfile, email=teacher_email)

        # Create and save feedback with rating and prediction
        Testimonial.objects.create(
            student=student,
            prediction=prediction,
            name=teacher.full_name,
            content=feedback_text,
            rating=rating
        )
        
        # Use HttpResponseRedirect with the full URL including query parameters
        return HttpResponseRedirect(reverse('teacher_dashboard') + '?feedback_success=true')

def student_feedback(request):
    # Check if user is logged in
    student_id = request.session.get('student_id')
    if not student_id:
        # If not logged in, redirect to signin page
        return redirect('student_signin')
    try:
        # Get the student profile
        student = StudentProfile.objects.get(id=student_id)
    except StudentProfile.DoesNotExist:
        # If student doesn't exist in DB (rare case), clear session and redirect
        request.session.flush()
        return redirect('student_signin')
    
    # Handle form submission
    if request.method == 'POST':
        content = request.POST.get('content')
        rating = request.POST.get('rating')
        
        # Validate the data
        if content and rating:
            # Create new feedback
            feedback = Testimonial.objects.create(
                student=student,
                name=student.full_name,
                content=content,
                rating=int(rating)
            )
            return redirect('home')  # Or redirect back to the feedback page
    
    # Get existing feedback from this student
    existing_feedback = Testimonial.objects.filter(student=student).order_by('-created_at')
    
    context = {
        'user': student,  # For consistent template rendering
        'existing_feedback': existing_feedback
    }
    
    return render(request, 'student_feedback.html', context)

def logout_view(request):
    logout(request)
    return redirect('landing')