import SimpleITK as sitk
import sys

# === INPUTS ===
contrast_path = sys.argv[1]
qalas_path = sys.argv[2]
b1_path = sys.argv[3]
output_b1_path = sys.argv[4]

# === LOAD IMAGES ===
contrast = sitk.ReadImage(contrast_path, sitk.sitkFloat32)
b1 = sitk.ReadImage(b1_path, sitk.sitkFloat32)

# Extract first 3D volume from QALAS 4D image
qalas_4d = sitk.ReadImage(qalas_path, sitk.sitkFloat32)
size_4d = qalas_4d.GetSize()
extractor = sitk.ExtractImageFilter()
extractor.SetSize([size_4d[0], size_4d[1], size_4d[2], 0])
extractor.SetIndex([0, 0, 0, 0])
qalas = extractor.Execute(qalas_4d)

# === INITIAL ALIGNMENT (CENTERED) ===
initial_transform = sitk.CenteredTransformInitializer(
    qalas,
    contrast,
    sitk.Euler3DTransform(),
    sitk.CenteredTransformInitializerFilter.GEOMETRY
)

# === REGISTRATION SETUP ===
registration = sitk.ImageRegistrationMethod()
registration.SetMetricAsMattesMutualInformation(numberOfHistogramBins=32)
registration.SetMetricSamplingStrategy(registration.RANDOM)
registration.SetMetricSamplingPercentage(0.2)
registration.SetInterpolator(sitk.sitkLinear)

registration.SetOptimizerAsRegularStepGradientDescent(
    learningRate=2.0,
    minStep=1e-4,
    numberOfIterations=200,
    gradientMagnitudeTolerance=1e-6
)
registration.SetOptimizerScalesFromPhysicalShift()
registration.SetInitialTransform(initial_transform, inPlace=False)

registration.SetShrinkFactorsPerLevel([4, 2, 1])
registration.SetSmoothingSigmasPerLevel([2, 1, 0])
registration.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()

# === EXECUTE REGISTRATION (contrast to QALAS) ===
final_transform = registration.Execute(qalas, contrast)

# === APPLY TO B1 MAP ===
b1_resampled = sitk.Resample(
    b1,
    qalas,
    final_transform,
    sitk.sitkLinear,
    0.0,
    b1.GetPixelID()
)

# === SAVE RESULT ===
sitk.WriteImage(b1_resampled, output_b1_path)
print("Registration complete. Resampled B1 map saved to:", output_b1_path)
